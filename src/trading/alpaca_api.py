"""Alpaca market-data facade — mirrors the HyperliquidAPI surface the
PaperBroker / trading_loop rely on, so paper-trading code can be reused
unchanged for US equities.

Read-only by design: this file never calls TradingClient.submit_order().
The PaperBroker still owns the fills; Alpaca is only the market-data
source.

Interface parity with HyperliquidAPI (subset used by main.py):
  - get_current_price(asset) -> float
  - get_candles(asset, interval, count) -> list[dict]  (ts/open/high/low/close/volume)
  - get_open_interest(asset) -> None           (N/A for stocks)
  - get_funding_rate(asset) -> None            (N/A for stocks)
  - get_meta_and_ctxs(dex=None) -> stub        (scanner currently off for stocks)
  - round_size(asset, amount) -> float         (fractional shares → 3dp)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
except Exception as e:  # pragma: no cover
    StockHistoricalDataClient = None
    DataFeed = None
    log.warning("alpaca-py not importable: %s", e)


_INTERVAL_MAP = {
    "1m": (1, "Minute"),
    "5m": (5, "Minute"),
    "15m": (15, "Minute"),
    "30m": (30, "Minute"),
    "1h": (1, "Hour"),
    "4h": (4, "Hour"),
    "1d": (1, "Day"),
}


class AlpacaAPI:
    def __init__(self) -> None:
        key = os.getenv("ALPACA_API_KEY_ID")
        secret = os.getenv("ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY missing — "
                "generate paper keys at https://app.alpaca.markets/paper/dashboard/overview"
            )
        if StockHistoricalDataClient is None:
            raise RuntimeError("alpaca-py not installed. Run: pip install alpaca-py")
        self._data = StockHistoricalDataClient(key, secret)

    def _tf(self, interval: str) -> "TimeFrame":
        amt, unit = _INTERVAL_MAP.get(interval, (1, "Hour"))
        return TimeFrame(amt, getattr(TimeFrameUnit, unit))

    async def get_current_price(self, asset: str) -> float:
        def _call():
            # IEX feed = free-tier real-time. SIP requires paid subscription.
            req = StockLatestTradeRequest(symbol_or_symbols=[asset], feed=DataFeed.IEX)
            resp = self._data.get_stock_latest_trade(req)
            trade = resp.get(asset)
            if trade is None:
                raise RuntimeError(f"No latest trade for {asset}")
            return float(trade.price)
        return await asyncio.to_thread(_call)

    async def get_candles(self, asset: str, interval: str = "5m", count: int = 100):
        tf = self._tf(interval)
        # pull a generous lookback window so we always fill `count` bars
        minutes_per = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
        lookback_min = minutes_per.get(interval, 60) * count * 3
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_min)

        def _call():
            req = StockBarsRequest(
                symbol_or_symbols=[asset], timeframe=tf, start=start, end=end,
                limit=count, feed=DataFeed.IEX,
            )
            bars = self._data.get_stock_bars(req)
            raw = bars.data.get(asset, [])
            out = []
            for b in raw[-count:]:
                out.append({
                    "t": int(b.timestamp.timestamp() * 1000),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume or 0),
                })
            return out

        return await asyncio.to_thread(_call)

    async def get_open_interest(self, asset: str):
        return None

    async def get_funding_rate(self, asset: str):
        return None

    async def get_meta_and_ctxs(self, dex: str | None = None):
        # Scanner not supported for stocks yet (universe is huge and different
        # metrics apply). Return shape that makes the scanner bail cleanly.
        return [{"universe": []}, []]

    def round_size(self, asset: str, amount: float) -> float:
        # Alpaca paper supports fractional shares to 9 decimals, but 3 is plenty.
        return round(float(amount), 3)
