"""
Hyperliquid Jarvis — live status publisher.

Snapshots account/positions/last decision to the sibling live-data git repo
after each trading loop iteration. Public Vercel dashboards (portfolio case
study + jarvis-dashboard fallback) can read this without needing the FastAPI
backend or tunnel to be up.

Failures never block the trading loop. Status is observability, not critical path.

Default location: C:\\Users\\Dev\\Desktop\\live-data\\
Override via LIVE_DATA_REPO_PATH env var.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("live_status")

# Trading folder layout: C:\Users\Dev\Desktop\Trading\src\
# live-data:             C:\Users\Dev\Desktop\live-data\
_DEFAULT_REPO = Path(__file__).resolve().parent.parent.parent / "live-data"
LIVE_DATA_REPO = Path(os.environ.get("LIVE_DATA_REPO_PATH", _DEFAULT_REPO))
PROJECT_DIR = LIVE_DATA_REPO / "trading"
LATEST = PROJECT_DIR / "latest.json"
HISTORY = PROJECT_DIR / "history.jsonl"

# Throttle: don't push more often than this (seconds). Trading loop may run
# every minute; pushing every minute spams the git history. 15 min is plenty.
MIN_INTERVAL_SECONDS = 900
_last_push_ts: float = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> tuple[int, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(LIVE_DATA_REPO), *args],
            capture_output=True, text=True, timeout=30,
        )
        return res.returncode, (res.stdout + res.stderr).strip()
    except Exception as e:
        return 1, f"git invocation error: {e}"


def record_snapshot(
    *,
    account_value: float | None,
    initial_balance: float | None,
    open_positions: list[dict],
    last_decision: dict | None = None,
    paper_mode: bool = True,
    force: bool = False,
) -> None:
    """
    Snapshot the trading agent's current state. Called once per loop iteration.
    Throttled internally to MIN_INTERVAL_SECONDS unless force=True.

    last_decision shape (optional): {asset, action, rationale, at}
    open_positions: list of dicts with keys coin, szi, entryPx, pnl, etc.
    """
    import time
    global _last_push_ts
    now_ts = time.time()
    if not force and (now_ts - _last_push_ts) < MIN_INTERVAL_SECONDS:
        return
    if not LIVE_DATA_REPO.exists():
        log.warning(f"live_status: repo not found at {LIVE_DATA_REPO} — skipping")
        return

    try:
        pnl_usd = None
        pnl_pct = None
        if account_value is not None and initial_balance:
            pnl_usd = round(account_value - initial_balance, 2)
            pnl_pct = round((account_value - initial_balance) / initial_balance * 100, 2)

        positions_clean = []
        for p in (open_positions or [])[:20]:
            coin = p.get("coin")
            if not coin:
                continue
            positions_clean.append({
                "asset": coin,
                "size": p.get("szi"),
                "entry": p.get("entryPx"),
                "tp": p.get("tp"),
                "sl": p.get("sl"),
                "unrealized_pnl": p.get("pnl"),
            })

        payload = {
            "updated_at": _now_iso(),
            "mode": "paper" if paper_mode else "live",
            "account": {
                "balance_usd": account_value,
                "total_value_usd": account_value,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
            },
            "open_positions": positions_clean,
            "last_decision": last_decision,
        }

        PROJECT_DIR.mkdir(parents=True, exist_ok=True)
        LATEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        # Append a thin history record (account value + pnl only — keeps file small)
        history_record = {
            "at": payload["updated_at"],
            "total_value": account_value,
            "pnl_pct": pnl_pct,
            "open_positions": len(positions_clean),
        }
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_record) + "\n")

        _git("pull", "--rebase", "--autostash")
        _git("add", "trading/latest.json", "trading/history.jsonl")
        rc, _ = _git("commit", "-m", "data(trading): snapshot")
        if rc == 0:
            _git("push")
            _last_push_ts = now_ts
            log.info("live_status: pushed trading snapshot")
    except Exception as e:
        log.warning(f"live_status: record_snapshot failed (non-fatal): {e}")
