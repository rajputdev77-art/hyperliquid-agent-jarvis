"""FastAPI app exposing paper-broker state to the dashboard.

Run in a background thread from main.py via uvicorn. State is injected
through `init_api(broker)`; the handlers close over it.
"""

from __future__ import annotations

import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.trading.paper_broker import PaperBroker


_broker: PaperBroker | None = None


def init_api(broker: PaperBroker) -> FastAPI:
    global _broker
    _broker = broker

    app = FastAPI(title="hyperliquid-agent-jarvis", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/account")
    async def account():
        state = await _broker.get_user_state()
        row = _broker._account_row()
        return {
            "initial_balance": float(row["initial_balance"]),
            "balance": state["balance"],
            "total_value": state["total_value"],
            "total_pnl": float(row["total_pnl"]),
            "daily_pnl": float(row["daily_pnl"]),
            "open_positions": len(state["positions"]),
        }

    @app.get("/positions")
    async def positions():
        state = await _broker.get_user_state()
        return {"positions": state["positions"]}

    @app.get("/history")
    def history(limit: int = 200):
        rows = _broker._conn.execute(
            "SELECT id, asset, side, size_asset, entry_price, close_price, "
            "tp_price, sl_price, opened_at, closed_at, close_reason, realized_pnl "
            "FROM positions WHERE status = 'closed' "
            "ORDER BY closed_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return {"trades": [dict(r) for r in rows]}

    @app.get("/decisions")
    def decisions(limit: int = 50):
        rows = _broker._conn.execute(
            "SELECT timestamp, cycle, asset, action, allocation_usd, rationale, "
            "exit_plan, reasoning, account_value "
            "FROM decisions ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return {"decisions": [dict(r) for r in rows]}

    return app
