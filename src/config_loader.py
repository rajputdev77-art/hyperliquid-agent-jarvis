"""Centralized environment config for hyperliquid-agent-jarvis.

Adapted from Sanket's loader: swapped Anthropic for Gemini, made Hyperliquid keys
optional (paper mode default), and added paper-trading knobs.
"""

import json
import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer for {name}: {raw}") from exc


def _get_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid float for {name}: {raw}") from exc


PAPER_MODE = _get_bool("PAPER_TRADING_MODE", True)

CONFIG = {
    # --- Master switch ---
    "paper_trading_mode": PAPER_MODE,

    # --- Paper broker ---
    "paper_starting_balance": _get_float("PAPER_STARTING_BALANCE", 1000.0),
    "paper_entry_slippage_pct": _get_float("PAPER_ENTRY_SLIPPAGE_PCT", 0.05),
    "database_path": _get("DATABASE_PATH", "./data/trades.db"),
    "llm_log_dir": _get("LLM_LOG_DIR", "./data/llm_logs"),
    "log_dir": _get("LOG_DIR", "./logs"),
    "log_level": _get("LOG_LEVEL", "INFO"),

    # --- LLM (Gemini) ---
    "llm_provider": _get("LLM_PROVIDER", "gemini"),
    "gemini_api_key": _get("GEMINI_API_KEY"),
    "llm_model": _get("LLM_MODEL", "gemini-2.5-flash-lite"),
    # Per-market overrides — fall back to llm_model if unset. Used so each
    # bot consumes its own daily quota bucket on the Gemini free tier.
    "llm_model_crypto": _get("LLM_MODEL_CRYPTO"),
    "llm_model_stocks": _get("LLM_MODEL_STOCKS"),
    "max_tokens": _get_int("MAX_TOKENS", 4096),

    # --- Hyperliquid (read-only in paper mode; not required) ---
    "hyperliquid_private_key": _get("HYPERLIQUID_PRIVATE_KEY"),
    "hyperliquid_vault_address": _get("HYPERLIQUID_VAULT_ADDRESS"),
    "hyperliquid_network": _get("HYPERLIQUID_NETWORK", "mainnet"),
    "hyperliquid_base_url": _get("HYPERLIQUID_BASE_URL"),

    # --- Runtime ---
    "assets": _get("ASSETS"),
    "interval": _get("INTERVAL", "1h"),

    # --- Opportunity scanner (stage-1 funnel over all Hyperliquid perps) ---
    "scan_enabled": _get_bool("SCAN_ENABLED", True),
    "scan_top_n": _get_int("SCAN_TOP_N", 15),

    # --- SL hygiene ---
    "min_sl_distance_pct": _get_float("MIN_SL_DISTANCE_PCT", 2.0),

    # --- Risk ---
    "max_position_pct": _get("MAX_POSITION_PCT", "10"),
    "max_loss_per_position_pct": _get("MAX_LOSS_PER_POSITION_PCT", "20"),
    "max_leverage": _get("MAX_LEVERAGE", "3"),
    "max_total_exposure_pct": _get("MAX_TOTAL_EXPOSURE_PCT", "50"),
    "daily_loss_circuit_breaker_pct": _get("DAILY_LOSS_CIRCUIT_BREAKER_PCT", "10"),
    "mandatory_sl_pct": _get("MANDATORY_SL_PCT", "5"),
    "max_concurrent_positions": _get("MAX_CONCURRENT_POSITIONS", "10"),
    "min_balance_reserve_pct": _get("MIN_BALANCE_RESERVE_PCT", "20"),

    # --- API ---
    "api_host": _get("API_HOST", "0.0.0.0"),
    "api_port": _get("API_PORT", "8000"),
}


def validate_config() -> None:
    """Fail fast on misconfig. Called from main.py at boot."""
    if CONFIG["llm_provider"] != "gemini":
        raise RuntimeError(
            f"Only Gemini is wired up. LLM_PROVIDER={CONFIG['llm_provider']}"
        )
    if not CONFIG["gemini_api_key"]:
        raise RuntimeError(
            "GEMINI_API_KEY missing. Get one free at https://aistudio.google.com/apikey"
        )
    if not CONFIG["assets"]:
        raise RuntimeError("ASSETS missing. Example: ASSETS=\"BTC ETH SOL\"")
    if not CONFIG["paper_trading_mode"]:
        raise RuntimeError(
            "This build is paper-only. Set PAPER_TRADING_MODE=true or refuse to start."
        )
