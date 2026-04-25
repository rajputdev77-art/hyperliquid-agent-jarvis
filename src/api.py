"""FastAPI app exposing paper-broker state to the dashboard.

Run in a background thread from main.py via uvicorn. State is injected
through `init_api(broker)`; the handlers close over it.

Crypto bot (port 8000) ALSO opens the stocks SQLite database read-only
and exposes /stocks/* + /combined/* endpoints, so the dashboard can show
both markets through one tunnel without needing the stocks bot to be
publicly reachable.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.trading.paper_broker import PaperBroker


_broker: PaperBroker | None = None
_stocks_db: sqlite3.Connection | None = None


def _open_stocks_db() -> sqlite3.Connection | None:
    """Open the stocks bot's SQLite DB read-only, if it exists.

    The stocks bot is a separate process writing to its own DB; we only
    READ from it here. Using `mode=ro` ensures we never lock or mutate.
    """
    path = os.getenv("STOCKS_DB_PATH", "./data/trades_stocks.db")
    if not pathlib.Path(path).exists():
        return None
    try:
        # immutable=0 so we still see writes the stocks bot makes after we open
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def init_api(broker: PaperBroker) -> FastAPI:
    global _broker, _stocks_db
    _broker = broker
    _stocks_db = _open_stocks_db()

    app = FastAPI(title="hyperliquid-agent-jarvis", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Landing page (HTML, replaces raw JSON)
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def root():
        return _LANDING_HTML

    @app.get("/health")
    def health():
        return {"ok": True, "stocks_db": _stocks_db is not None}

    # ------------------------------------------------------------------
    # Crypto endpoints (this process owns the broker)
    # ------------------------------------------------------------------
    @app.get("/account")
    async def account():
        return await _account_payload(broker_arg=_broker)

    @app.get("/positions")
    async def positions():
        state = await _broker.get_user_state()
        return {"positions": state["positions"]}

    @app.get("/history")
    def history(limit: int = 200):
        return {"trades": _query_history(_broker._conn, limit)}

    @app.get("/decisions")
    def decisions(limit: int = 50):
        return {"decisions": _query_decisions(_broker._conn, limit)}

    # ------------------------------------------------------------------
    # Stocks endpoints (read the stocks bot's DB directly)
    # ------------------------------------------------------------------
    @app.get("/stocks/account")
    def stocks_account():
        if _stocks_db is None:
            return {"error": "stocks bot not running yet"}
        row = _stocks_db.execute("SELECT * FROM account WHERE id = 1").fetchone()
        if row is None:
            return {"error": "stocks DB has no account row"}
        positions, unrealized = _stocks_open_positions()
        balance = float(row["balance"])
        return {
            "initial_balance": float(row["initial_balance"]),
            "balance": balance,
            "total_value": balance + unrealized,
            "total_pnl": float(row["total_pnl"]),
            "daily_pnl": float(row["daily_pnl"]),
            "open_positions": len(positions),
        }

    @app.get("/stocks/positions")
    def stocks_positions():
        if _stocks_db is None:
            return {"positions": []}
        positions, _ = _stocks_open_positions()
        return {"positions": positions}

    @app.get("/stocks/history")
    def stocks_history(limit: int = 200):
        if _stocks_db is None:
            return {"trades": []}
        return {"trades": _query_history(_stocks_db, limit)}

    @app.get("/stocks/decisions")
    def stocks_decisions(limit: int = 50):
        if _stocks_db is None:
            return {"decisions": []}
        return {"decisions": _query_decisions(_stocks_db, limit)}

    # ------------------------------------------------------------------
    # Combined: aggregate balance + PnL across both markets
    # ------------------------------------------------------------------
    @app.get("/combined/account")
    async def combined_account():
        crypto = await _account_payload(broker_arg=_broker)
        stocks = stocks_account() if _stocks_db is not None else None
        if stocks and "error" in stocks:
            stocks = None
        out = {
            "crypto": crypto,
            "stocks": stocks,
        }
        if stocks:
            out["total"] = {
                "initial_balance": crypto["initial_balance"] + stocks["initial_balance"],
                "balance": crypto["balance"] + stocks["balance"],
                "total_value": crypto["total_value"] + stocks["total_value"],
                "total_pnl": crypto["total_pnl"] + stocks["total_pnl"],
                "daily_pnl": crypto["daily_pnl"] + stocks["daily_pnl"],
                "open_positions": crypto["open_positions"] + stocks["open_positions"],
            }
        else:
            out["total"] = crypto
        return out

    return app


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

async def _account_payload(broker_arg: PaperBroker) -> dict:
    state = await broker_arg.get_user_state()
    row = broker_arg._account_row()
    return {
        "initial_balance": float(row["initial_balance"]),
        "balance": state["balance"],
        "total_value": state["total_value"],
        "total_pnl": float(row["total_pnl"]),
        "daily_pnl": float(row["daily_pnl"]),
        "open_positions": len(state["positions"]),
    }


def _stocks_open_positions() -> tuple[list[dict], float]:
    """Read open stock positions from the stocks DB. Unrealized PnL uses
    the most recent close price stored in candles_snapshots, falling back
    to entry price when unavailable (so the dashboard shows zeros rather
    than NaNs)."""
    if _stocks_db is None:
        return [], 0.0
    rows = _stocks_db.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
    out: list[dict] = []
    unrealized = 0.0
    for r in rows:
        asset = r["asset"]
        last = _stocks_db.execute(
            "SELECT close_price FROM candles_snapshots WHERE asset = ? "
            "ORDER BY id DESC LIMIT 1",
            (asset,),
        ).fetchone()
        last_px = float(last["close_price"]) if last and last["close_price"] is not None else float(r["entry_price"])
        qty = float(r["size_asset"])
        entry = float(r["entry_price"])
        signed = qty if r["side"] == "long" else -qty
        pnl = (last_px - entry) * qty if r["side"] == "long" else (entry - last_px) * qty
        unrealized += pnl
        out.append({
            "coin": asset,
            "szi": signed,
            "entryPx": entry,
            "pnl": pnl,
            "notional_entry": qty * entry,
            "leverage": float(r["leverage"] or 1),
            "liquidationPx": None,
            "tp_price": r["tp_price"],
            "sl_price": r["sl_price"],
        })
    return out, unrealized


def _query_history(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, asset, side, size_asset, entry_price, close_price, "
        "tp_price, sl_price, opened_at, closed_at, close_reason, realized_pnl "
        "FROM positions WHERE status = 'closed' "
        "ORDER BY closed_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def _query_decisions(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT timestamp, cycle, asset, action, allocation_usd, rationale, "
        "exit_plan, reasoning, account_value "
        "FROM decisions ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------
# Landing page
# ----------------------------------------------------------------------
_LANDING_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>jarvis · paper-trading agent</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root { color-scheme: dark; }
  body { background: #0b0e14; color: #e5e7eb; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; padding: 40px; max-width: 720px; margin: 0 auto; }
  h1 { color: #22d3ee; margin: 0 0 4px; font-size: 28px; }
  .sub { color: #6b7280; margin-bottom: 32px; }
  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  a.card { display: block; background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; text-decoration: none; color: #e5e7eb; transition: transform .15s, border-color .15s; }
  a.card:hover { transform: translateY(-2px); border-color: #22d3ee; }
  .card .ep { color: #22d3ee; font-weight: 600; font-size: 14px; }
  .card .desc { color: #9ca3af; font-size: 12px; margin-top: 4px; }
  .badge { display: inline-block; background: #064e3b; color: #6ee7b7; padding: 2px 8px; border-radius: 999px; font-size: 11px; margin-left: 8px; vertical-align: middle; }
  h2 { color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin: 32px 0 8px; }
</style>
</head>
<body>
  <h1>jarvis <span class="badge">paper-mode</span></h1>
  <div class="sub">Hyperliquid + US-stocks paper-trading agent · LLM-in-the-loop</div>

  <h2>Crypto (Hyperliquid)</h2>
  <div class="grid">
    <a class="card" href="/account"><div class="ep">/account</div><div class="desc">balance, PnL, open count</div></a>
    <a class="card" href="/positions"><div class="ep">/positions</div><div class="desc">live positions w/ TP/SL</div></a>
    <a class="card" href="/history"><div class="ep">/history?limit=50</div><div class="desc">closed trades</div></a>
    <a class="card" href="/decisions"><div class="ep">/decisions?limit=20</div><div class="desc">LLM rationale per cycle</div></a>
  </div>

  <h2>Stocks (Alpaca)</h2>
  <div class="grid">
    <a class="card" href="/stocks/account"><div class="ep">/stocks/account</div><div class="desc">balance, PnL, open count</div></a>
    <a class="card" href="/stocks/positions"><div class="ep">/stocks/positions</div><div class="desc">live positions</div></a>
    <a class="card" href="/stocks/history"><div class="ep">/stocks/history?limit=50</div><div class="desc">closed trades</div></a>
    <a class="card" href="/stocks/decisions"><div class="ep">/stocks/decisions?limit=20</div><div class="desc">LLM rationale</div></a>
  </div>

  <h2>Combined</h2>
  <div class="grid">
    <a class="card" href="/combined/account"><div class="ep">/combined/account</div><div class="desc">total balance + PnL across markets</div></a>
    <a class="card" href="/health"><div class="ep">/health</div><div class="desc">liveness ping</div></a>
  </div>
</body>
</html>"""
