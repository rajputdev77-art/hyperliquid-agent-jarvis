"""Groq-backed decision maker.

Drop-in replacement for the Gemini/Ollama DecisionMaker. Same public contract.
Uses Groq's OpenAI-compatible chat API — fast (~1s) and generous free tier
(14,400 requests/day on Llama 3.3 70B as of 2026-05).
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from datetime import datetime, timezone

import requests

from src.config_loader import CONFIG

log = logging.getLogger(__name__)

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
    "Your goal: decisive, first-principles decisions per asset that minimize "
    "churn while capturing edge.\n\n"
    "Output contract\n"
    "- Output ONLY a strict JSON object — no markdown, no code fences, no prose.\n"
    "- Exactly two top-level keys:\n"
    "  * \"reasoning\": long-form string.\n"
    "  * \"trade_decisions\": array ordered to match the provided assets list.\n"
    "- Each trade_decisions item MUST contain: asset, action (buy/sell/hold), "
    "allocation_usd, order_type (market/limit), limit_price, tp_price, sl_price, "
    "exit_plan, rationale."
)


class GroqDecisionMaker:
    """Groq-backed replacement. Same interface as Gemini/Ollama."""

    def __init__(self, hyperliquid=None, model_override: str | None = None):
        self.api_key = (
            CONFIG.get("groq_api_key")
            or os.getenv("GROQ_API_KEY")
            or ""
        )
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY missing in .env")
        self.model_name = (
            model_override
            or CONFIG.get("llm_model")
            or "llama-3.3-70b-versatile"
        )
        self.max_tokens = int(CONFIG.get("max_tokens") or 4096)
        self.hyperliquid = hyperliquid
        self.log_dir = pathlib.Path(CONFIG.get("llm_log_dir") or "./data/llm_logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def decide_trade(self, assets: list[str], context: str) -> dict:
        return self.get_decision(assets, context)

    def get_decision(self, assets: list[str], context: str) -> dict:
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(assets=json.dumps(list(assets)))
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
            "temperature": 0.3,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        raw_text = ""
        error_msg: str | None = None
        for attempt in (1, 2, 3):
            try:
                r = requests.post(self.endpoint, json=payload, headers=headers, timeout=120)
                if r.status_code == 429:
                    log.warning("Groq 429 (rate limit), waiting 30s before retry %s", attempt)
                    time.sleep(30)
                    continue
                r.raise_for_status()
                data = r.json()
                raw_text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                break
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                log.warning("Groq call failed (attempt %s): %s", attempt, error_msg)
                if attempt < 3:
                    time.sleep(5)
                    continue
                break

        parsed = self._parse(raw_text, assets)
        self._log_call(assets, system_prompt, context, raw_text, parsed, error_msg)
        return parsed

    def _parse(self, raw_text: str, assets: list[str]) -> dict:
        if not raw_text:
            return self._all_hold(assets, "empty response")

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            nl = cleaned.find("\n")
            cleaned = cleaned[nl + 1:] if nl >= 0 else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("Groq JSON parse error: %s; raw: %s", e, raw_text[:300])
            return self._all_hold(assets, f"parse error: {e}")

        if not isinstance(obj, dict):
            return self._all_hold(assets, "non-object response")

        reasoning = str(obj.get("reasoning") or "")
        decisions_raw = obj.get("trade_decisions")
        if not isinstance(decisions_raw, list):
            return self._all_hold(assets, "missing trade_decisions")

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
                    "rationale": f"hold-all: {reason}",
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
        error_msg: str | None,
    ) -> None:
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log_file = self.log_dir / f"groq_{ts}.json"
            log_file.write_text(
                json.dumps(
                    {
                        "model": self.model_name,
                        "assets": assets,
                        "system_prompt": system_prompt,
                        "user_context": context,
                        "raw_response": raw_text,
                        "parsed": parsed,
                        "error": error_msg,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
