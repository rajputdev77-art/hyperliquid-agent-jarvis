"""Paper-trading broker.

Exposes the same public method names Sanket's main loop expects from
`HyperliquidAPI`, but all order-placement methods write to SQLite instead
of submitting to the real exchange. Market-data reads are delegated to
an internal read-only `HyperliquidAPI` instance.

Tables (created on first run in DATABASE_PATH):

  account           — single row with balance, pnl, daily pnl
  positions         — every paper position, open and closed
  orders            — pending/filled/canceled sub-orders (limit, TP, SL)
  decisions         — LLM cycle log: rationale + indicator snapshot
  candles_snapshots — the per-cycle indicator snapshot, for reproducibility

Safety invariant: this file MUST NOT import the live Exchange SDK class
and MUST NOT call any `self.hl.exchange.*` method. Only the read-only
Info client is used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from src.config_loader import CONFIG
from src.trading.hyperliquid_api import HyperliquidAPI

log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    initial_balance REAL NOT NULL,
    balance REAL NOT NULL,
    total_pnl REAL NOT NULL DEFAULT 0,
    daily_pnl REAL NOT NULL DEFAULT 0,
    daily_reset_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    size_asset REAL NOT NULL,
    entry_price REAL NOT NULL,
    leverage REAL NOT NULL DEFAULT 1,
    tp_price REAL,
    sl_price REAL,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')) DEFAULT 'open',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    close_price REAL,
    close_reason TEXT,
    realized_pnl REAL
);

CREATE INDEX IF NOT EXISTS positions_status_idx ON positions(status);
CREATE INDEX IF NOT EXISTS positions_asset_idx ON positions(asset);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oid INTEGER UNIQUE NOT NULL,
    asset TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK (order_type IN ('market', 'limit', 'tp', 'sl')),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    size_asset REAL NOT NULL,
    price REAL,
    trigger_px REAL,
    reduce_only INTEGER DEFAULT 0,
    parent_position_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('open', 'filled', 'canceled')) DEFAULT 'open',
    created_at TEXT NOT NULL,
    filled_at TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cycle INTEGER,
    asset TEXT,
    action TEXT,
    allocation_usd REAL,
    rationale TEXT,
    exit_plan TEXT,
    reasoning TEXT,
    indicator_snapshot_json TEXT,
    account_value REAL
);

CREATE TABLE IF NOT EXISTS candles_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    asset TEXT NOT NULL,
    close_price REAL,
    indicators_json TEXT
);
"""


class PaperBroker:
    """SQLite-backed paper trading broker.

    Public API mirrors the subset of `HyperliquidAPI` that `main.py` uses.
    Market-data methods delegate to an internal read-only `HyperliquidAPI`.
    """

    def __init__(self) -> None:
        self.db_path = pathlib.Path(CONFIG.get("database_path") or "./data/trades.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.slippage_pct = float(CONFIG.get("paper_entry_slippage_pct") or 0.0)
        self.initial_balance = float(CONFIG.get("paper_starting_balance") or 1000.0)
        self._oid_seq = int(time.time() * 1000)  # monotonic fake order id

        # Read-only market-data client
        self.hl = HyperliquidAPI()

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._init_account_row()

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    def _init_account_row(self) -> None:
        row = self._conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO account (id, initial_balance, balance, daily_reset_date, created_at) "
                "VALUES (1, ?, ?, ?, ?)",
                (
                    self.initial_balance,
                    self.initial_balance,
                    datetime.now(timezone.utc).date().isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _next_oid(self) -> int:
        self._oid_seq += 1
        return self._oid_seq

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Account state
    # ------------------------------------------------------------------

    def _account_row(self) -> sqlite3.Row:
        return self._conn.execute("SELECT * FROM account WHERE id = 1").fetchone()

    def _update_balance(self, new_balance: float, pnl_delta: float) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._account_row()
        reset_date = row["daily_reset_date"]
        daily_pnl = row["daily_pnl"]
        if reset_date != today:
            daily_pnl = 0.0
            reset_date = today
        daily_pnl += pnl_delta
        self._conn.execute(
            "UPDATE account SET balance = ?, total_pnl = total_pnl + ?, "
            "daily_pnl = ?, daily_reset_date = ? WHERE id = 1",
            (new_balance, pnl_delta, daily_pnl, reset_date),
        )

    def _open_positions(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM positions WHERE status = 'open'"
        ).fetchall()

    # ------------------------------------------------------------------
    # Mark-to-market: call once per loop BEFORE the LLM decision.
    # ------------------------------------------------------------------

    async def mark_to_market(self) -> dict[str, float]:
        """Refresh unrealized PnL, auto-close TP/SL hits, return {asset: price}.

        Returns the latest price per asset currently held — saves an extra
        Info call later in the loop.
        """
        prices: dict[str, float] = {}
        for pos in self._open_positions():
            asset = pos["asset"]
            if asset not in prices:
                try:
                    prices[asset] = await self.hl.get_current_price(asset)
                except Exception as e:
                    log.warning("Mark-to-market price fetch failed for %s: %s", asset, e)
                    continue
            px = prices[asset]
            tp = pos["tp_price"]
            sl = pos["sl_price"]
            side = pos["side"]
            hit: str | None = None
            if side == "long":
                if sl is not None and px <= sl:
                    hit = "sl"
                elif tp is not None and px >= tp:
                    hit = "tp"
            else:  # short
                if sl is not None and px >= sl:
                    hit = "sl"
                elif tp is not None and px <= tp:
                    hit = "tp"
            if hit:
                close_px = sl if hit == "sl" else tp
                self._close_position(pos, float(close_px), reason=hit)
        return prices

    def _close_position(self, pos: sqlite3.Row, close_price: float, reason: str) -> None:
        qty = float(pos["size_asset"])
        entry = float(pos["entry_price"])
        if pos["side"] == "long":
            pnl = (close_price - entry) * qty
        else:
            pnl = (entry - close_price) * qty
        close_price_with_slip = self._apply_slippage(
            close_price, is_buy=(pos["side"] == "short")
        )
        self._conn.execute(
            "UPDATE positions SET status = 'closed', closed_at = ?, "
            "close_price = ?, close_reason = ?, realized_pnl = ? WHERE id = ?",
            (self._now(), close_price_with_slip, reason, pnl, pos["id"]),
        )
        new_balance = float(self._account_row()["balance"]) + pnl
        self._update_balance(new_balance, pnl)

        # Cancel any pending TP/SL orders tied to this position
        self._conn.execute(
            "UPDATE orders SET status = 'canceled' WHERE parent_position_id = ? AND status = 'open'",
            (pos["id"],),
        )
        log.info(
            "[paper] closed %s %s qty=%.6f entry=%.4f exit=%.4f pnl=%.2f reason=%s",
            pos["asset"], pos["side"], qty, entry, close_price, pnl, reason,
        )

    def _apply_slippage(self, px: float, is_buy: bool) -> float:
        if self.slippage_pct <= 0:
            return px
        k = 1 + (self.slippage_pct / 100.0) * (1 if is_buy else -1)
        return px * k

    # ------------------------------------------------------------------
    # Order placement — main contract
    # ------------------------------------------------------------------

    async def place_buy_order(self, asset: str, amount: float, slippage: float = 0.01) -> dict:
        return await self._market_open(asset, is_buy=True, amount=amount)

    async def place_sell_order(self, asset: str, amount: float, slippage: float = 0.01) -> dict:
        return await self._market_open(asset, is_buy=False, amount=amount)

    async def place_limit_buy(self, asset: str, amount: float, limit_price: float, tif: str = "Gtc") -> dict:
        return self._record_limit(asset, is_buy=True, amount=amount, limit_price=limit_price)

    async def place_limit_sell(self, asset: str, amount: float, limit_price: float, tif: str = "Gtc") -> dict:
        return self._record_limit(asset, is_buy=False, amount=amount, limit_price=limit_price)

    async def place_take_profit(self, asset: str, is_buy: bool, amount: float, tp_price: float) -> dict:
        """`is_buy` reflects the original entry side; TP closes the opposite side."""
        pos_id = self._attach_trigger(asset, is_long_entry=is_buy, tp=tp_price, sl=None)
        oid = self._next_oid()
        self._conn.execute(
            "INSERT INTO orders (oid, asset, order_type, side, size_asset, price, trigger_px, "
            "reduce_only, parent_position_id, status, created_at) "
            "VALUES (?, ?, 'tp', ?, ?, ?, ?, 1, ?, 'open', ?)",
            (oid, asset, "sell" if is_buy else "buy", amount, tp_price, tp_price, pos_id, self._now()),
        )
        return self._fake_order_response(oid, resting=True)

    async def place_stop_loss(self, asset: str, is_buy: bool, amount: float, sl_price: float) -> dict:
        pos_id = self._attach_trigger(asset, is_long_entry=is_buy, tp=None, sl=sl_price)
        oid = self._next_oid()
        self._conn.execute(
            "INSERT INTO orders (oid, asset, order_type, side, size_asset, price, trigger_px, "
            "reduce_only, parent_position_id, status, created_at) "
            "VALUES (?, ?, 'sl', ?, ?, ?, ?, 1, ?, 'open', ?)",
            (oid, asset, "sell" if is_buy else "buy", amount, sl_price, sl_price, pos_id, self._now()),
        )
        return self._fake_order_response(oid, resting=True)

    async def cancel_order(self, asset: str, oid: int) -> dict:
        self._conn.execute(
            "UPDATE orders SET status = 'canceled' WHERE oid = ? AND status = 'open'",
            (oid,),
        )
        return {"status": "ok", "oid": oid}

    async def cancel_all_orders(self, asset: str) -> dict:
        cur = self._conn.execute(
            "UPDATE orders SET status = 'canceled' WHERE asset = ? AND status = 'open'",
            (asset,),
        )
        return {"status": "ok", "cancelled_count": cur.rowcount}

    # ------------------------------------------------------------------
    # Internal: create / update positions
    # ------------------------------------------------------------------

    async def _market_open(self, asset: str, is_buy: bool, amount: float) -> dict:
        px = await self.hl.get_current_price(asset)
        fill_px = self._apply_slippage(px, is_buy=is_buy)
        side = "long" if is_buy else "short"
        cur = self._conn.execute(
            "INSERT INTO positions (asset, side, size_asset, entry_price, leverage, "
            "opened_at, status) VALUES (?, ?, ?, ?, ?, ?, 'open')",
            (asset, side, abs(amount), fill_px, 1.0, self._now()),
        )
        pos_id = cur.lastrowid
        oid = self._next_oid()
        self._conn.execute(
            "INSERT INTO orders (oid, asset, order_type, side, size_asset, price, "
            "reduce_only, parent_position_id, status, created_at, filled_at) "
            "VALUES (?, ?, 'market', ?, ?, ?, 0, ?, 'filled', ?, ?)",
            (oid, asset, "buy" if is_buy else "sell", amount, fill_px, pos_id, self._now(), self._now()),
        )
        log.info("[paper] OPEN %s %s qty=%.6f @ %.4f (slipped from %.4f)",
                 side, asset, amount, fill_px, px)
        return self._fake_order_response(oid, resting=False, filled_px=fill_px)

    def _record_limit(self, asset: str, is_buy: bool, amount: float, limit_price: float) -> dict:
        """Store a resting limit order. Fill logic fires in `mark_to_market_limits`."""
        oid = self._next_oid()
        self._conn.execute(
            "INSERT INTO orders (oid, asset, order_type, side, size_asset, price, "
            "reduce_only, status, created_at) VALUES (?, ?, 'limit', ?, ?, ?, 0, 'open', ?)",
            (oid, asset, "buy" if is_buy else "sell", amount, limit_price, self._now()),
        )
        log.info("[paper] LIMIT %s %s qty=%.6f @ %.4f (resting)",
                 "buy" if is_buy else "sell", asset, amount, limit_price)
        return self._fake_order_response(oid, resting=True)

    def _attach_trigger(self, asset: str, is_long_entry: bool, tp: float | None, sl: float | None) -> int | None:
        """Link TP/SL to the most recent open position for this asset, and store the price."""
        row = self._conn.execute(
            "SELECT id FROM positions WHERE asset = ? AND status = 'open' "
            "ORDER BY id DESC LIMIT 1",
            (asset,),
        ).fetchone()
        if row is None:
            return None
        if tp is not None:
            self._conn.execute("UPDATE positions SET tp_price = ? WHERE id = ?", (tp, row["id"]))
        if sl is not None:
            self._conn.execute("UPDATE positions SET sl_price = ? WHERE id = ?", (sl, row["id"]))
        return row["id"]

    @staticmethod
    def _fake_order_response(oid: int, resting: bool, filled_px: float | None = None) -> dict:
        status = {"resting": {"oid": oid}} if resting else {"filled": {"oid": oid, "avgPx": filled_px or 0}}
        return {
            "status": "ok",
            "response": {
                "type": "order",
                "data": {"statuses": [status]},
            },
        }

    def extract_oids(self, order_result: Any) -> list[int]:
        """Mirror HyperliquidAPI.extract_oids so callers don't special-case."""
        oids: list[int] = []
        try:
            statuses = order_result["response"]["data"]["statuses"]
            for st in statuses:
                for k in ("resting", "filled"):
                    if k in st and "oid" in st[k]:
                        oids.append(st[k]["oid"])
        except (KeyError, TypeError):
            pass
        return oids

    # ------------------------------------------------------------------
    # State queries (shape matches HyperliquidAPI.get_user_state)
    # ------------------------------------------------------------------

    async def get_user_state(self) -> dict:
        account = self._account_row()
        positions_out: list[dict] = []
        total_unrealized = 0.0
        for pos in self._open_positions():
            try:
                px = await self.hl.get_current_price(pos["asset"])
            except Exception:
                px = float(pos["entry_price"])
            qty = float(pos["size_asset"])
            entry = float(pos["entry_price"])
            signed_size = qty if pos["side"] == "long" else -qty
            pnl = (px - entry) * qty if pos["side"] == "long" else (entry - px) * qty
            total_unrealized += pnl
            positions_out.append({
                "coin": pos["asset"],
                "szi": signed_size,
                "entryPx": entry,
                "pnl": pnl,
                "notional_entry": qty * entry,
                "leverage": float(pos["leverage"] or 1),
                "liquidationPx": None,
                "tp_price": pos["tp_price"],
                "sl_price": pos["sl_price"],
            })
        balance = float(account["balance"])
        total_value = balance + total_unrealized
        return {"balance": balance, "total_value": total_value, "positions": positions_out}

    async def get_open_orders(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE status = 'open' ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "coin": r["asset"],
                "oid": r["oid"],
                "isBuy": r["side"] == "buy",
                "sz": r["size_asset"],
                "px": r["price"],
                "triggerPx": r["trigger_px"],
                "orderType": r["order_type"],
            })
        return out

    async def get_recent_fills(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE status = 'filled' ORDER BY filled_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        fills = []
        for r in rows:
            ts = r["filled_at"] or r["created_at"]
            try:
                t_ms = int(datetime.fromisoformat(ts).timestamp() * 1000)
            except Exception:
                t_ms = int(time.time() * 1000)
            fills.append({
                "coin": r["asset"],
                "isBuy": r["side"] == "buy",
                "sz": r["size_asset"],
                "px": r["price"],
                "time": t_ms,
            })
        return fills

    # ------------------------------------------------------------------
    # Market-data passthrough (read-only — delegated to Hyperliquid Info)
    # ------------------------------------------------------------------

    async def get_current_price(self, asset: str) -> float:
        return await self.hl.get_current_price(asset)

    async def get_candles(self, asset: str, interval: str = "5m", count: int = 100):
        return await self.hl.get_candles(asset, interval, count)

    async def get_open_interest(self, asset: str):
        return await self.hl.get_open_interest(asset)

    async def get_funding_rate(self, asset: str):
        return await self.hl.get_funding_rate(asset)

    async def get_meta_and_ctxs(self, dex: str | None = None):
        return await self.hl.get_meta_and_ctxs(dex=dex)

    def round_size(self, asset: str, amount: float) -> float:
        return self.hl.round_size(asset, amount)

    # ------------------------------------------------------------------
    # Decision + snapshot logging
    # ------------------------------------------------------------------

    def log_cycle(
        self,
        *,
        cycle: int,
        reasoning: str,
        decisions: list[dict],
        account_value: float,
        indicator_snapshots: list[dict],
    ) -> None:
        now = self._now()
        for d in decisions:
            self._conn.execute(
                "INSERT INTO decisions (timestamp, cycle, asset, action, allocation_usd, "
                "rationale, exit_plan, reasoning, indicator_snapshot_json, account_value) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now, cycle, d.get("asset"), d.get("action"),
                    float(d.get("allocation_usd") or 0),
                    d.get("rationale") or "",
                    d.get("exit_plan") or "",
                    reasoning,
                    None,
                    account_value,
                ),
            )
        for snap in indicator_snapshots:
            self._conn.execute(
                "INSERT INTO candles_snapshots (timestamp, asset, close_price, indicators_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    now,
                    snap.get("asset"),
                    float(snap.get("close_price") or 0) if snap.get("close_price") is not None else None,
                    json.dumps(snap.get("indicators") or {}, default=str),
                ),
            )


# Keep the module import side-effect-free for paper safety.
assert "Exchange" not in globals(), "PaperBroker must not import the live Exchange class."
