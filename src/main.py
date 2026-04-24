"""hyperliquid-agent-jarvis entry-point.

Boot order:
  1. Load .env, validate config, enforce PAPER_TRADING_MODE.
  2. Build PaperBroker (wraps a read-only Hyperliquid Info client).
  3. Build Gemini DecisionMaker + RiskManager.
  4. Start FastAPI on port 8000 in a background thread.
  5. Enter trading loop: mark-to-market → gather indicators → Gemini →
     risk check → route orders through broker → log.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import pathlib
import signal
import sys
import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone

import uvicorn

from src.agent.decision_maker import DecisionMaker
from src.api import init_api
from src.config_loader import CONFIG, validate_config
from src.indicators.local_indicators import compute_all, last_n, latest
from src.risk_manager import RiskManager
from src.trading.paper_broker import PaperBroker
from src.utils.prompt_utils import json_default, round_or_none, round_series


# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    log_dir = pathlib.Path(CONFIG.get("log_dir") or "./logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, (CONFIG.get("log_level") or "INFO").upper(), logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "agent.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    # clear any default handlers so duplicate lines don't show
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s :: %(message)s"))
    root.addHandler(stream)
    return logging.getLogger("jarvis")


log = _setup_logging()


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _interval_seconds(s: str) -> int:
    if not s:
        raise ValueError("INTERVAL empty")
    unit = s[-1].lower()
    n = int(s[:-1])
    if unit == "m": return n * 60
    if unit == "h": return n * 3600
    if unit == "d": return n * 86400
    raise ValueError(f"bad interval: {s}")


def _parse_assets(raw: str | None, cli_assets: list[str] | None) -> list[str]:
    if cli_assets:
        return cli_assets
    if not raw:
        return []
    if "," in raw:
        return [a.strip() for a in raw.split(",") if a.strip()]
    return [a.strip() for a in raw.split() if a.strip()]


# --------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------

async def trading_loop(broker: PaperBroker, agent: DecisionMaker, risk: RiskManager,
                       assets: list[str], interval_s: int) -> None:
    log.info("Starting loop — assets=%s interval=%ss", assets, interval_s)
    invocation = 0
    initial_value: float | None = None
    price_history: dict[str, deque] = {a: deque(maxlen=60) for a in assets}

    await broker.get_meta_and_ctxs()  # warm cache

    while True:
        invocation += 1
        try:
            # 1. Mark-to-market any open positions (auto-close TP/SL)
            cached_prices = await broker.mark_to_market()

            # 2. Account snapshot
            state = await broker.get_user_state()
            account_value = state["total_value"]
            if initial_value is None:
                initial_value = account_value
            total_return_pct = (
                (account_value - initial_value) / initial_value * 100.0
                if initial_value else 0.0
            )

            # 3. Force-close ugly positions via risk manager
            for ptc in risk.check_losing_positions(state["positions"]):
                coin = ptc["coin"]
                size = ptc["size"]
                is_long = ptc["is_long"]
                log.warning("RISK FORCE-CLOSE %s at %s%% loss", coin, ptc["loss_pct"])
                if is_long:
                    await broker.place_sell_order(coin, size)
                else:
                    await broker.place_buy_order(coin, size)
                await broker.cancel_all_orders(coin)

            # 4. Gather indicators per asset
            market_sections: list[dict] = []
            asset_prices: dict[str, float] = {}
            indicator_snapshots: list[dict] = []
            for asset in assets:
                try:
                    current_price = cached_prices.get(asset) or await broker.get_current_price(asset)
                    asset_prices[asset] = current_price
                    price_history[asset].append(round_or_none(current_price, 4))

                    candles_5m = await broker.get_candles(asset, "5m", 100)
                    candles_4h = await broker.get_candles(asset, "4h", 100)
                    intra = compute_all(candles_5m)
                    lt = compute_all(candles_4h)
                    funding = await broker.get_funding_rate(asset)
                    oi = await broker.get_open_interest(asset)

                    section = {
                        "asset": asset,
                        "current_price": round_or_none(current_price, 4),
                        "intraday": {
                            "ema20": round_or_none(latest(intra.get("ema20", [])), 4),
                            "macd": round_or_none(latest(intra.get("macd", [])), 4),
                            "rsi7": round_or_none(latest(intra.get("rsi7", [])), 2),
                            "rsi14": round_or_none(latest(intra.get("rsi14", [])), 2),
                            "series": {
                                "ema20": round_series(last_n(intra.get("ema20", []), 10), 4),
                                "rsi14": round_series(last_n(intra.get("rsi14", []), 10), 2),
                                "macd": round_series(last_n(intra.get("macd", []), 10), 4),
                            },
                        },
                        "long_term": {
                            "ema20": round_or_none(latest(lt.get("ema20", [])), 4),
                            "ema50": round_or_none(latest(lt.get("ema50", [])), 4),
                            "atr14": round_or_none(latest(lt.get("atr14", [])), 4),
                            "rsi14": round_or_none(latest(lt.get("rsi14", [])), 2),
                        },
                        "open_interest": round_or_none(oi, 2),
                        "funding_rate": round_or_none(funding, 8),
                        "recent_mid_prices": list(price_history[asset])[-10:],
                    }
                    market_sections.append(section)
                    indicator_snapshots.append({
                        "asset": asset,
                        "close_price": current_price,
                        "indicators": section,
                    })
                except Exception as e:
                    log.exception("Data gather failed for %s: %s", asset, e)

            # 5. Build LLM context
            context_payload = OrderedDict([
                ("invocation", {
                    "count": invocation,
                    "current_time": datetime.now(timezone.utc).isoformat(),
                }),
                ("account", {
                    "balance": round_or_none(state["balance"], 2),
                    "total_value": round_or_none(account_value, 2),
                    "total_return_pct": round(total_return_pct, 2),
                    "positions": state["positions"],
                }),
                ("risk_limits", risk.get_risk_summary()),
                ("market_data", market_sections),
                ("instructions", {
                    "assets": assets,
                    "requirement": "Return a strict JSON object per the schema.",
                }),
            ])
            context = json.dumps(context_payload, default=json_default)

            # 6. Call Gemini
            outputs = agent.decide_trade(assets, context)
            reasoning = outputs.get("reasoning", "") if isinstance(outputs, dict) else ""

            # 7. Execute via paper broker with risk validation
            for out in outputs.get("trade_decisions", []):
                try:
                    asset = out.get("asset")
                    if asset not in assets:
                        continue
                    action = out.get("action", "hold")
                    if action == "hold":
                        log.info("HOLD %s: %s", asset, out.get("rationale", ""))
                        continue

                    current_price = asset_prices.get(asset, 0.0)
                    out["current_price"] = current_price
                    allowed, reason, out = risk.validate_trade(out, state, initial_value or 0)
                    if not allowed:
                        log.warning("RISK BLOCKED %s: %s", asset, reason)
                        continue

                    alloc_usd = float(out.get("allocation_usd", 0))
                    if alloc_usd <= 0 or current_price <= 0:
                        continue
                    amount = alloc_usd / current_price
                    is_buy = action == "buy"

                    order_type = out.get("order_type", "market")
                    limit_price = out.get("limit_price")
                    if order_type == "limit" and limit_price:
                        if is_buy:
                            await broker.place_limit_buy(asset, amount, float(limit_price))
                        else:
                            await broker.place_limit_sell(asset, amount, float(limit_price))
                    else:
                        if is_buy:
                            await broker.place_buy_order(asset, amount)
                        else:
                            await broker.place_sell_order(asset, amount)

                    if out.get("tp_price"):
                        await broker.place_take_profit(asset, is_buy, amount, float(out["tp_price"]))
                    if out.get("sl_price"):
                        await broker.place_stop_loss(asset, is_buy, amount, float(out["sl_price"]))
                    log.info("%s %s alloc=$%.2f amt=%.6f @ ~%.4f",
                             action.upper(), asset, alloc_usd, amount, current_price)
                except Exception as e:
                    log.exception("Execution failed for %s: %s", out.get("asset"), e)

            # 8. Log the cycle
            broker.log_cycle(
                cycle=invocation,
                reasoning=reasoning,
                decisions=outputs.get("trade_decisions", []),
                account_value=account_value,
                indicator_snapshots=indicator_snapshots,
            )

        except Exception as loop_err:
            log.exception("Loop iteration failed: %s", loop_err)

        await asyncio.sleep(interval_s)


# --------------------------------------------------------------------
# Boot
# --------------------------------------------------------------------

def _start_api_thread(broker: PaperBroker) -> threading.Thread:
    app = init_api(broker)
    host = CONFIG.get("api_host") or "0.0.0.0"
    port = int(CONFIG.get("api_port") or 8000)
    cfg = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True, name="api")
    t.start()
    log.info("API serving on http://%s:%s", host, port)
    return t


def main() -> None:
    validate_config()

    # Hard paper-mode assertion — this is a paper-only build.
    assert CONFIG["paper_trading_mode"] is True, (
        "Refusing to start: PAPER_TRADING_MODE must be true in this build."
    )

    parser = argparse.ArgumentParser(description="hyperliquid-agent-jarvis (paper)")
    parser.add_argument("--assets", nargs="+")
    parser.add_argument("--interval")
    args = parser.parse_args()

    assets = _parse_assets(CONFIG.get("assets"), args.assets)
    interval = args.interval or CONFIG.get("interval") or "1h"
    if not assets:
        parser.error("ASSETS missing. Set in .env or pass --assets.")
    interval_s = _interval_seconds(interval)

    broker = PaperBroker()
    agent = DecisionMaker(hyperliquid=broker.hl)
    risk = RiskManager()
    _start_api_thread(broker)

    def _bye(_signum=None, _frame=None):
        log.info("Stopping.")
        sys.exit(0)
    signal.signal(signal.SIGINT, _bye)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _bye)

    asyncio.run(trading_loop(broker, agent, risk, assets, interval_s))


if __name__ == "__main__":
    main()
