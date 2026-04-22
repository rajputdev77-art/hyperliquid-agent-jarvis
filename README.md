# hyperliquid-agent-jarvis

AI paper-trading agent for Hyperliquid perpetual futures. LLM driver = Google Gemini 2.5 Flash (free tier). Trade execution = local SQLite `PaperBroker` — **no real money moves**. Market data fetched live from Hyperliquid (read-only).

Runs on Oracle Cloud Free Tier. Dashboard on Vercel free tier. Total monthly cost: ₹0.

## Why

Portfolio case study on LLM-in-the-loop decision making. Goal is rigorous paper-traded evidence, not production trading.

## Architecture (one-liner)

```
Hyperliquid (candles) → indicators → Gemini → PaperBroker (SQLite)
                                            └→ FastAPI → Next.js dashboard
```

Full breakdown: [ARCHITECTURE_NOTES.md](ARCHITECTURE_NOTES.md).

## Quick start (local)

```bash
# 1. Install Python 3.12 and Poetry
poetry install

# 2. Copy env template, fill in GEMINI_API_KEY
cp .env.example .env
# then edit .env

# 3. Run
poetry run python -m src.main
```

API comes up on `http://localhost:8000`:
- `GET /account` — balance, total pnl, daily pnl
- `GET /positions` — open positions
- `GET /history` — closed trades
- `GET /decisions?limit=50` — recent LLM decisions w/ reasoning
- `GET /health` — liveness

## Deploy

See [DEPLOY.md](DEPLOY.md) — Oracle Cloud + systemd + Vercel dashboard.

## Case study

See [case_study.md](case_study.md) + `analysis/case_study.ipynb`.

## Paper-mode guarantee

`main.py` asserts `PAPER_TRADING_MODE=true` at boot. `PaperBroker` is the only broker ever imported when the flag is on. Real-order methods on `HyperliquidAPI` are monkey-patched to raise.
