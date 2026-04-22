# ARCHITECTURE_NOTES — Sanket's Hyperliquid Trading Agent

Reference repo: https://github.com/sanketagarwal/hyperliquid-trading-agent
Cloned at: `/tmp/reference-repo`

## Source tree (what exists)

```
src/
  main.py                     # Trading loop + aiohttp server
  config_loader.py            # Loads .env into CONFIG dict
  risk_manager.py             # Hard risk checks (size, leverage, drawdown, SL)
  agent/decision_maker.py     # Claude API caller (TradingAgent)
  indicators/
    local_indicators.py       # EMA, RSI, MACD, ATR, BBands, ADX, OBV, VWAP etc.
    taapi_client.py           # Legacy remote indicator client (unused now)
  trading/hyperliquid_api.py  # Exchange + Info SDK wrapper (data + orders)
  utils/
    formatting.py             # fmt, fmt_sz helpers
    prompt_utils.py           # json_default, round_or_none, round_series
```

**No `dashboard/` folder exists in this repo.** Prompt assumed one. We build fresh.

## `main.py` — the trading loop

Entry: `main()` parses CLI (`--assets BTC ETH SOL --interval 1h`), falls back to `.env` (`ASSETS`, `INTERVAL`). Then:

1. Builds `HyperliquidAPI()`, `TradingAgent(hyperliquid=...)`, `RiskManager()`.
2. Starts `aiohttp` server exposing `GET /diary`, `GET /logs`.
3. `run_loop()` — async while-true:
   - Pulls `get_user_state()` (balance, positions, pnl).
   - Runs `risk_mgr.check_losing_positions(...)` → force-closes anything past max-loss, fires `place_sell_order`/`place_buy_order`.
   - Fetches per-asset: `get_current_price`, `get_open_interest`, `get_funding_rate`, 5m + 4h candles → `compute_all(...)` indicators.
   - Assembles single `context_payload` (JSON) → `agent.decide_trade(assets, context)`.
   - Retries once if parse error.
   - For each decision: `risk_mgr.validate_trade(...)` → if ok → places market or limit order via `hyperliquid.place_buy_order` / `place_sell_order` / `place_limit_buy` / `place_limit_sell`; then `place_take_profit`, `place_stop_loss`.
   - Writes `diary.jsonl`, `decisions.jsonl`, `prompts.log`, `llm_requests.log`.
   - Sleeps `INTERVAL` seconds.

**Real-money chokepoints (all in `src/trading/hyperliquid_api.py`):**
- `place_buy_order` → `self.exchange.market_open(asset, True, amount, None, slippage)`
- `place_sell_order` → `self.exchange.market_open(asset, False, ...)`
- `place_limit_buy` / `place_limit_sell` → `self.exchange.order(...)`
- `place_take_profit` / `place_stop_loss` → `self.exchange.order(...)` with `trigger` order type
- `cancel_order`, `cancel_all_orders` → `self.exchange.cancel(...)`

**Read-only (safe to keep in paper mode):**
- `get_user_state`, `get_current_price`, `get_open_interest`, `get_funding_rate`, `get_candles`, `get_meta_and_ctxs`, `get_open_orders`, `get_recent_fills`.

Paper plan: `PaperBroker` implements same method names but writes to SQLite. `main.py` factory picks between them by `PAPER_TRADING_MODE`. The real `HyperliquidAPI` keeps read-only methods; order methods raise when paper mode is on, as defense-in-depth.

## `agent/decision_maker.py` — Claude layer (to be replaced)

Class `TradingAgent`:
- Method: `decide_trade(assets, context) -> dict`.
- Returns:
  ```json
  {
    "reasoning": "<long-form string>",
    "trade_decisions": [
      {"asset": "BTC", "action": "buy|sell|hold",
       "allocation_usd": 120.0, "order_type": "market|limit",
       "limit_price": null, "tp_price": ..., "sl_price": ...,
       "exit_plan": "...", "rationale": "..."}
    ]
  }
  ```
- Internals:
  - Big `system_prompt` (lines 31–85 of decision_maker.py) — trader persona, low-churn policy, hysteresis rule, cooldown rule, TP/SL sanity, leverage policy, JSON output contract.
  - Claude tool: `fetch_indicator` (optional, enabled by `ENABLE_TOOL_CALLING`). Tool loop up to 6 iterations.
  - Sanitizer fallback: a cheap Haiku call (`_sanitize_output`) that extracts JSON if main call returns prose.
  - Fills defaults: `allocation_usd=0`, `order_type=market`, `limit_price=null`, `tp/sl=null`, `exit_plan=""`, `rationale=""`.
  - Logs every request to `llm_requests.log`.

**Gemini port plan (Phase 2):**
- Preserve method signature `decide_trade(assets, context) -> dict` exactly.
- Same system prompt (copy verbatim — it's doing real work).
- Use `google-generativeai` with `gemini-2.5-flash`. Ask for JSON only via `response_mime_type="application/json"` + response schema.
- Drop Claude tool-calling for MVP (Gemini tool-calling differs; start without tools — system has pre-computed indicators per loop anyway).
- On parse error: return `{"reasoning": "parse error", "trade_decisions": [{asset, "hold", 0, ...}, ...]}` — same shape as Sanket's fallback.
- On rate-limit (`429`): sleep 60s, retry once, then `[]` hold-all.
- Log every call to `./data/llm_logs/YYYY-MM-DD.jsonl` (timestamp, prompt, raw response, parsed).

## `risk_manager.py` — hard safety guards

`RiskManager` config (all from `.env`):
- `max_position_pct` (default 10)
- `max_loss_per_position_pct` (default 20)
- `max_leverage` (default 10)
- `max_total_exposure_pct` (default 50)
- `daily_loss_circuit_breaker_pct` (default 10)
- `mandatory_sl_pct` (default 5)
- `max_concurrent_positions` (default 10)
- `min_balance_reserve_pct` (default 20)

Key methods we reuse unmodified:
- `validate_trade(trade, account_state, initial_balance)` — runs daily-drawdown, reserve, size cap, exposure, leverage, concurrent-positions checks; enforces mandatory SL; may adjust `allocation_usd` down to cap. Returns `(allowed, reason, adjusted_trade)`.
- `check_losing_positions(positions)` — returns list of positions past `max_loss_per_position_pct` for force-close.
- `get_risk_summary()` — dict for LLM context.

These need zero changes for paper mode — they operate on dicts, not real exchange calls.

## `indicators/local_indicators.py`

Exposes `compute_all(candles) -> dict` returning keys:
`ema20`, `ema50`, `rsi7`, `rsi14`, `macd`, `macd_signal`, `macd_histogram`, `atr3`, `atr14`, `bbands_upper/middle/lower`, `adx`, `obv`, `vwap`, `stoch_rsi` (subset per SDK version). Plus helpers `latest(series)`, `last_n(series, n)`. Copy verbatim.

## Things we deliberately change for our build

| Piece | Original | Ours |
|---|---|---|
| LLM | Claude Sonnet 4 | Gemini 2.5 Flash (free tier) |
| Trade execution | Real Hyperliquid orders | `PaperBroker` → SQLite |
| Config loader | `ANTHROPIC_API_KEY` required | `GEMINI_API_KEY` required; Hyperliquid key optional in paper mode |
| Logs | `diary.jsonl`, `decisions.jsonl` flat files | SQLite `account`, `positions`, `decisions`, `candles_snapshots` tables + JSONL LLM log |
| HTTP server | aiohttp, `/diary` + `/logs` | FastAPI on :8000, `/account`, `/positions`, `/history`, `/decisions`, `/health` |
| Dashboard | none in repo | Fresh minimal Next.js (Vercel) |
| Deploy | `Dockerfile` for container | Oracle Cloud Free Tier + systemd service |

## Files copied verbatim to our project (Phase 1)

- `src/indicators/local_indicators.py`
- `src/utils/formatting.py`
- `src/utils/prompt_utils.py`
- `src/risk_manager.py`
- `src/trading/hyperliquid_api.py` (keep as market-data-only client; paper mode assertion in `main.py` forbids order methods)

## Files rewritten

- `src/agent/decision_maker.py` — Gemini version.
- `src/config_loader.py` — Gemini + paper-mode fields.
- `src/main.py` — FastAPI server, paper-broker factory, SQLite logging.
- `src/trading/paper_broker.py` — new file.

## Open questions for user (none blocking right now)

- Track funding-rate cost in paper mode? **Default: no** (adds complexity, not material at 1h intervals). Can revisit.
- Track slippage in paper mode? **Default: apply 0.05% fixed slippage on entry/exit** so paper numbers aren't unrealistically clean.
- `max_concurrent_positions` set to `3` (one per asset) in paper mode? **Default: keep 10** so LLM can stack if it chooses.
