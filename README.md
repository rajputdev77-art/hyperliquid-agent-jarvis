# hyperliquid-agent-jarvis

LLM-in-the-loop paper-trading agent for Hyperliquid perpetual futures. Market data pulled live from Hyperliquid's public REST/WebSocket API; trade decisions made by Google **Gemini 2.5 Flash Lite** (free tier, no card); every "trade" filled into a local SQLite `PaperBroker` — **no real money ever moves**.

Total running cost: ₹0/month (Gemini free tier + SQLite + Vercel Hobby + a laptop OR Fly.io/Render free tier).

Companion dashboard: **[rajputdev77-art/jarvis-dashboard](https://github.com/rajputdev77-art/jarvis-dashboard)** (Next.js 14, deploys to Vercel).

## What it does, in order

Every `INTERVAL` (default 1 h) the bot:

1. **Mark to market.** Check open positions, auto-close any that hit their take-profit or stop-loss price.
2. **Pull market state.** For each asset in `ASSETS=BTC ETH SOL`: 5-minute and 4-hour candles from Hyperliquid, plus funding rate and open interest. Compute indicators locally: EMA, RSI, MACD, ATR, Bollinger, ADX, OBV, VWAP.
3. **Ask Gemini.** Package account state + per-asset indicators + risk limits + recent history into one prompt. Demand a strict JSON response: one decision per asset (`buy`/`sell`/`hold`, allocation in USD, order type, TP, SL, exit plan, rationale), plus long-form reasoning.
4. **Validate.** `RiskManager` rejects any decision that violates the hard limits (position-size cap, total exposure, leverage, daily drawdown circuit breaker, mandatory stop-loss). The LLM cannot override these.
5. **Fill.** Surviving orders → `PaperBroker` → SQLite row at live mid-price + 0.05% slippage.
6. **Log.** Every indicator snapshot, every rationale, every decision, every simulated fill → SQLite, so a Jupyter notebook can reconstruct exactly what the model saw months later.

## Paper-mode guarantee (can it accidentally trade live?)

No. Three layers:

1. `main.py` asserts `PAPER_TRADING_MODE=true` at boot — hard-fails if not.
2. When the flag is on, `HyperliquidAPI.exchange = None` — the object the live SDK uses to submit orders is literally absent. Any attempt to call an order method raises `AttributeError` before reaching the SDK.
3. The dependency-injected broker is `PaperBroker`, which writes to SQLite. The live `Exchange` class is never imported in this path.

## Quick start — local (5 min)

```bash
# 1. Python 3.11, 3.12 or 3.13 (3.12 preferred)
py -3.13 -m venv .venv
.venv\Scripts\activate

# 2. Deps
pip install hyperliquid-python-sdk google-genai python-dotenv aiohttp pandas numpy fastapi "uvicorn[standard]" requests matplotlib seaborn

# 3. Env — paste your free Gemini key
copy .env.example .env
# then edit .env : GEMINI_API_KEY=AIza... (grab one from https://aistudio.google.com/apikey)

# 4. Run
python -m src.main
```

Or double-click **`start.bat`** in this folder.

API comes up on `http://localhost:8000`:

| route | purpose |
|---|---|
| `GET /health` | liveness ping |
| `GET /account` | balance, total_value, pnl |
| `GET /positions` | open positions with TP/SL |
| `GET /history` | closed trades |
| `GET /decisions?limit=50` | recent LLM decisions with rationale + reasoning |

## Dashboard

The Next.js dashboard lives in its own repo: **[rajputdev77-art/jarvis-dashboard](https://github.com/rajputdev77-art/jarvis-dashboard)**. Deploy with one click to Vercel. Point `NEXT_PUBLIC_API_URL` at your backend URL.

## Hosting — zero-cost options

[HOSTING.md](HOSTING.md) walks through six options (Windows PC, Fly.io, Render, Railway, GitHub Codespaces, Oracle Cloud) step by step. **TL;DR: just run it on your laptop with `start.bat` and expose via Cloudflare Tunnel.**

## Case study

The point of the project is producing a dataset, then studying it.

- **Notebook**: [analysis/case_study.ipynb](analysis/case_study.ipynb) — trade stats, per-asset breakdown, equity curve, drawdown, LLM keyword quality, buy-and-hold baseline.
- **Writeup**: [case_study.md](case_study.md) — 1,500 words, Mermaid architecture diagram, honest conclusions.

Both are placeholders for the "what I learned / what I'd do differently" sections until 4 weeks of live data accumulate.

## Architecture deep-dive

[ARCHITECTURE_NOTES.md](ARCHITECTURE_NOTES.md) — which parts of Sanket Agarwal's [hyperliquid-trading-agent](https://github.com/sanketagarwal/hyperliquid-trading-agent) this project keeps, which it replaces, and where the real-money chokepoints are.

## Risk limits (all hard-enforced)

| setting | default | role |
|---|---|---|
| `MAX_POSITION_PCT` | 10 | single position ≤ 10% of account |
| `MAX_TOTAL_EXPOSURE_PCT` | 50 | all positions ≤ 50% of account |
| `MAX_LEVERAGE` | 3 | cap leverage (tighter than live default) |
| `MAX_LOSS_PER_POSITION_PCT` | 20 | force-close at –20% |
| `DAILY_LOSS_CIRCUIT_BREAKER_PCT` | 10 | flip to all-hold at –10% intraday |
| `MANDATORY_SL_PCT` | 5 | auto-SL if LLM omits one |
| `MAX_CONCURRENT_POSITIONS` | 10 | hard cap on open trades |
| `MIN_BALANCE_RESERVE_PCT` | 20 | keep ≥ 20% free margin |

## License

MIT. Built on the structure of Sanket Agarwal's [hyperliquid-trading-agent](https://github.com/sanketagarwal/hyperliquid-trading-agent) — Claude-based decision logic swapped for Gemini and real execution wrapped in a paper broker.
