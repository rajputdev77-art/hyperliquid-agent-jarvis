"""Gemini-backed decision maker.

Same public contract as Sanket's Claude `TradingAgent`:
    method: decide_trade(assets: list[str], context: str) -> dict
    return shape:
        {
          "reasoning": str,
          "trade_decisions": [
              { "asset", "action" ("buy"|"sell"|"hold"),
                "allocation_usd", "order_type" ("market"|"limit"),
                "limit_price", "tp_price", "sl_price",
                "exit_plan", "rationale" }, ...
          ]
        }
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from datetime import datetime, timezone

import google.generativeai as genai

from src.config_loader import CONFIG

log = logging.getLogger(__name__)


# System prompt lifted verbatim from Sanket's decision_maker, minus the
# Claude-specific tool bullet. Gemini gets pre-computed indicators in context.
_SYSTEM_PROMPT_TEMPLATE = (
    "You are a rigorous QUANTITATIVE TRADER and interdisciplinary "
    "MATHEMATICIAN-ENGINEER optimizing risk-adjusted returns for perpetual "
    "futures under real execution, margin, and funding constraints.\n"
    "You will receive market + account context for SEVERAL assets, including:\n"
    "- assets = {assets}\n"
    "- per-asset intraday (5m) and higher-timeframe (4h) metrics\n"
    "- Active Trades with Exit Plans\n"
    "- Recent Trading History\n"
    "- Risk management limits (hard-enforced by the system, not just guidelines)\n\n"
    "Always use the 'current time' provided in the user message to evaluate any "
    "time-based conditions, such as cooldown expirations or timed exit plans.\n\n"
    "Your goal: make decisive, first-principles decisions per asset that "
    "minimize churn while capturing edge. Aggressively pursue setups where "
    "calculated risk is outweighed by expected edge; size positions so downside "
    "is controlled while upside remains meaningful.\n\n"
    "Core policy (low-churn, position-aware)\n"
    "1) Respect prior plans: If an active trade has an exit_plan with explicit "
    "invalidation, DO NOT close or flip early unless that invalidation has occurred.\n"
    "2) Hysteresis: Require stronger evidence to CHANGE a decision than to keep it. "
    "Only flip direction if BOTH higher-timeframe structure supports the new "
    "direction AND intraday structure confirms with a decisive break beyond "
    "~0.5×ATR and momentum alignment. Otherwise, prefer HOLD or adjust TP/SL.\n"
    "3) Cooldown: After opening, adding, reducing, or flipping, impose a "
    "self-cooldown of at least 3 bars of the decision timeframe before another "
    "direction change, unless a hard invalidation occurs. Encode this in exit_plan.\n"
    "4) Funding is a tilt, not a trigger: do NOT flip solely due to funding.\n"
    "5) Overbought/oversold ≠ reversal by itself: treat RSI extremes as "
    "risk-of-pullback. Prefer tightening stops or partial profits over instant flips.\n"
    "6) Prefer adjustments over exits: if the thesis weakens but is not invalidated, "
    "tighten stop, trail TP, or reduce size before flipping.\n\n"
    "Decision discipline (per asset)\n"
    "- Choose one: buy / sell / hold.\n"
    "- allocation_usd — the system caps this per risk limits.\n"
    "- order_type: \"market\" (immediate) or \"limit\" (resting). limit_price required if limit.\n"
    "- TP/SL sanity:\n"
    "  * BUY: tp_price > current_price, sl_price < current_price\n"
    "  * SELL: tp_price < current_price, sl_price > current_price\n"
    "  Null is allowed; system will auto-apply mandatory SL.\n"
    "- exit_plan must include at least ONE explicit invalidation trigger.\n\n"
    "Leverage policy\n"
    "- Stay within the hard cap. In high volatility or funding spikes, reduce leverage.\n"
    "- Treat allocation_usd as notional.\n\n"
    "Reasoning recipe\n"
    "- Structure (trend, EMAs, HH/HL vs LH/LL). Momentum (MACD regime, RSI slope). "
    "Liquidity/volatility (ATR, volume). Positioning tilt (funding, OI). "
    "Favor alignment across 4h and 5m.\n\n"
    "Output contract\n"
    "- Output ONLY a strict JSON object — no markdown, no code fences, no prose.\n"
    "- Exactly two top-level keys:\n"
    "  * \"reasoning\": long-form string.\n"
    "  * \"trade_decisions\": array ordered to match the provided assets list.\n"
    "- Each trade_decisions item MUST contain: asset, action, allocation_usd, "
    "order_type, limit_price, tp_price, sl_price, exit_plan, rationale.\n"
    "- Do not add extra properties. Do not emit Markdown."
)


class DecisionMaker:
    """Gemini-backed replacement for Sanket's Claude `TradingAgent`."""

    def __init__(self, hyperliquid=None):
        api_key = CONFIG.get("gemini_api_key")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY missing. Set it in .env.")
        genai.configure(api_key=api_key)
        self.model_name = CONFIG.get("llm_model") or "gemini-2.5-flash"
        self.max_tokens = int(CONFIG.get("max_tokens") or 4096)
        self.hyperliquid = hyperliquid  # not used for tool calls in this port
        self.log_dir = pathlib.Path(CONFIG.get("llm_log_dir") or "./data/llm_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # Public contract -------------------------------------------------

    def decide_trade(self, assets: list[str], context: str) -> dict:
        """Backwards-compatible alias for main.py (mirrors Sanket's API)."""
        return self.get_decision(assets, context)

    def get_decision(self, assets: list[str], context: str) -> dict:
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(assets=json.dumps(list(assets)))
        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": self.max_tokens,
                "response_mime_type": "application/json",
            },
        )

        raw_text = ""
        error_msg: str | None = None
        for attempt in (1, 2):
            try:
                response = model.generate_content(context)
                raw_text = (response.text or "").strip()
                break
            except Exception as exc:  # includes 429 rate-limit
                error_msg = f"{type(exc).__name__}: {exc}"
                log.warning("Gemini call failed (attempt %s): %s", attempt, error_msg)
                if "429" in str(exc) or "rate" in str(exc).lower():
                    time.sleep(60)
                    continue
                break

        parsed = self._parse(raw_text, assets)
        self._log_call(assets, system_prompt, context, raw_text, parsed, error_msg)
        return parsed

    # Internals -------------------------------------------------------

    def _parse(self, raw_text: str, assets: list[str]) -> dict:
        if not raw_text:
            return self._all_hold(assets, reason="empty response")

        # Strip ``` fences defensively, even though response_mime_type=json should
        # make that unnecessary.
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            nl = cleaned.find("\n")
            cleaned = cleaned[nl + 1:] if nl >= 0 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("Gemini JSON parse error: %s; raw: %s", e, raw_text[:300])
            return self._all_hold(assets, reason=f"parse error: {e}")

        if not isinstance(obj, dict):
            return self._all_hold(assets, reason="non-object response")

        reasoning = str(obj.get("reasoning") or "")
        decisions_raw = obj.get("trade_decisions")
        if not isinstance(decisions_raw, list):
            return self._all_hold(assets, reason="missing trade_decisions")

        normalized: list[dict] = []
        for item in decisions_raw:
            if not isinstance(item, dict):
                continue
            item.setdefault("allocation_usd", 0.0)
            item.setdefault("order_type", "market")
            item.setdefault("limit_price", None)
            item.setdefault("tp_price", None)
            item.setdefault("sl_price", None)
            item.setdefault("exit_plan", "")
            item.setdefault("rationale", "")
            if item.get("action") not in {"buy", "sell", "hold"}:
                item["action"] = "hold"
            normalized.append(item)

        return {"reasoning": reasoning, "trade_decisions": normalized}

    def _all_hold(self, assets: list[str], reason: str) -> dict:
        return {
            "reasoning": f"Hold-all fallback: {reason}",
            "trade_decisions": [
                {
                    "asset": a,
                    "action": "hold",
                    "allocation_usd": 0.0,
                    "order_type": "market",
                    "limit_price": None,
                    "tp_price": None,
                    "sl_price": None,
                    "exit_plan": "",
                    "rationale": reason,
                }
                for a in assets
            ],
        }

    def _log_call(
        self,
        assets: list[str],
        system_prompt: str,
        context: str,
        raw_text: str,
        parsed: dict,
        error: str | None,
    ) -> None:
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = self.log_dir / f"{day}.jsonl"
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "model": self.model_name,
                "assets": list(assets),
                "system_prompt": system_prompt,
                "prompt": context,
                "raw_response": raw_text,
                "parsed": parsed,
                "error": error,
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.warning("LLM log write failed: %s", e)


# Back-compat alias so callers that imported Sanket's class name keep working.
TradingAgent = DecisionMaker
