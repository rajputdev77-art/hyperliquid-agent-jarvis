"""Hyperliquid opportunity scanner.

Stage-1 of a two-stage funnel: look at ALL Hyperliquid perps (~200) once per
cycle, rank them by a cheap volatility/volume/funding score, and return the
top-N for the LLM to deep-analyse. This prevents us from either (a) missing
obvious setups outside the three hand-picked symbols, or (b) blowing the
Gemini token budget by sending all 200 markets to the model.

Score intuition:
  - prefer markets actually moving (|24h return|)
  - prefer markets with real liquidity (24h notional volume > VOL_FLOOR)
  - bonus for funding rate extremes (crowd-trade signal, optional tilt)
  - penalise ultra-thin books (meta.maxLeverage is low → we'd slippage ourselves)

Everything here is PURE DATA — no orders, no decisions. Safe to run any time.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.trading.paper_broker import PaperBroker

log = logging.getLogger(__name__)

# Minimum 24h notional volume (USD) to even consider a market.
# Hyperliquid lists lots of long-tail memecoins with <$500k/day — useless for us.
VOL_FLOOR_USD = 1_000_000.0

# Skip anything whose mark price is under this (dust tokens) — rounding error
# dominates P&L noise at sub-cent prices.
PRICE_FLOOR = 0.0001


def _to_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _score_candidate(meta_entry: dict, ctx: dict) -> tuple[float, dict] | None:
    """Compute opportunity score for one market. Returns (score, summary) or None."""
    name = meta_entry.get("name")
    if not name:
        return None

    mark = _to_float(ctx.get("markPx"))
    prev = _to_float(ctx.get("prevDayPx"))
    vol = _to_float(ctx.get("dayNtlVlm"))
    oi = _to_float(ctx.get("openInterest"))
    funding = _to_float(ctx.get("funding"))
    max_lev = _to_float(meta_entry.get("maxLeverage"), default=1.0)

    if mark < PRICE_FLOOR or prev <= 0 or vol < VOL_FLOOR_USD:
        return None

    return_pct = (mark - prev) / prev * 100.0
    abs_move = abs(return_pct)

    # log-volume so a $100M market isn't 100x a $1M market in the score
    vol_tier = math.log10(max(vol, 1.0))

    # funding-tilt bonus: spot extreme positioning. Funding > 0.05% / 8h on the
    # long side often signals a squeezable setup (or a crowded trade about to
    # unwind). Scale modestly so funding doesn't dominate movement.
    funding_bonus = min(abs(funding) * 10_000, 2.0)  # caps at +2.0

    # Lev cap matters: a 3x-max market has 3x worse slippage & funding realities
    # than a 50x-max market of the same symbol. Shrink thinly-tradable names.
    lev_factor = min(max_lev / 10.0, 1.0)

    score = abs_move * vol_tier * (1.0 + funding_bonus) * lev_factor

    summary = {
        "asset": name,
        "score": round(score, 3),
        "mark_px": mark,
        "return_24h_pct": round(return_pct, 3),
        "vol_24h_usd": round(vol, 0),
        "open_interest": round(oi, 2) if oi else None,
        "funding_8h": round(funding, 6),
        "max_leverage": max_lev,
    }
    return score, summary


async def discover_opportunities(
    broker: "PaperBroker",
    top_n: int,
    always_include: list[str] | None = None,
) -> list[str]:
    """Return top-N asset names ranked by opportunity score.

    ``always_include`` is a safety list: symbols we want to keep evaluating
    every cycle regardless of their rank (so open positions are never dropped
    out of the prompt mid-trade). Open-position symbols should be passed here.
    """
    always_include = list(always_include or [])
    try:
        data = await broker.get_meta_and_ctxs()
    except Exception as e:
        log.warning("Scanner: meta fetch failed, falling back to always_include: %s", e)
        return list(dict.fromkeys(always_include))

    if not isinstance(data, list) or len(data) < 2:
        log.warning("Scanner: unexpected meta shape, falling back")
        return list(dict.fromkeys(always_include))

    meta, ctxs = data[0], data[1]
    universe = meta.get("universe") or []

    scored: list[tuple[float, dict]] = []
    for idx, m in enumerate(universe):
        if idx >= len(ctxs):
            continue
        scored_entry = _score_candidate(m, ctxs[idx])
        if scored_entry:
            scored.append(scored_entry)

    # sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked_names = [s[1]["asset"] for s in scored]

    # Compose final list: always_include first (dedup), then top candidates
    # that aren't already included, up to top_n total.
    seen: set[str] = set()
    out: list[str] = []
    for name in always_include:
        if name and name not in seen:
            out.append(name)
            seen.add(name)
    for name in ranked_names:
        if len(out) >= top_n:
            break
        if name not in seen:
            out.append(name)
            seen.add(name)

    # Log the short summary for post-hoc analysis
    top_summaries = [s[1] for s in scored[: max(top_n * 2, 20)]]
    log.info(
        "Scanner: %d markets above floor, top %d = %s",
        len(scored),
        len(out),
        [s["asset"] for s in top_summaries[:top_n]],
    )
    return out


async def scan_details(broker: "PaperBroker") -> list[dict]:
    """Return the full ranked summary list — for logging / analysis.

    Not used in the hot path, but handy for the notebook and for an eventual
    /scanner endpoint on the dashboard.
    """
    data = await broker.get_meta_and_ctxs()
    if not isinstance(data, list) or len(data) < 2:
        return []
    meta, ctxs = data[0], data[1]
    universe = meta.get("universe") or []
    scored: list[tuple[float, dict]] = []
    for idx, m in enumerate(universe):
        if idx >= len(ctxs):
            continue
        entry = _score_candidate(m, ctxs[idx])
        if entry:
            scored.append(entry)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored]
