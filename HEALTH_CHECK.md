# Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `systemctl status hyperliquid-agent` = **failed** | `journalctl -u hyperliquid-agent -n 200` | Usually a missing env var. Edit `.env`, then `sudo systemctl restart hyperliquid-agent`. |
| `curl http://<IP>:8000/health` times out from laptop | Oracle Security List lacks rule | Add ingress rule: `0.0.0.0/0 tcp dport=8000`. |
| `curl http://<IP>:8000/health` returns 000 but `localhost` works | `ufw` blocking | `sudo ufw allow 8000/tcp`. |
| Logs: `RuntimeError: GEMINI_API_KEY missing` | `.env` empty or `EnvironmentFile=` path wrong | Re-check `.env`. Then `sudo systemctl restart hyperliquid-agent`. |
| Dashboard shows `error: Failed to fetch` | Mixed-content (HTTPS → HTTP) | Enable Caddy or Cloudflare Tunnel per DEPLOY.md §4. |
| Gemini returns `429` continually | Free-tier quota hit (250/day) | Increase `INTERVAL` to `1h` or higher. |
| Service restarts every ~30s | Crash loop — check logs | `tail -200 logs/agent.log`. Common: bad `ASSETS` symbol. |
| `sqlite3.OperationalError: database is locked` | Another process has the DB open | `ps aux \| grep main`. Kill extras; service should run single instance. |
| Dashboard "updated" time frozen | API thread died but main loop alive | `journalctl -u hyperliquid-agent -f`. Restart service. |
| VM out of RAM | `free -h` | Free-tier ARM has 24 GB so this shouldn't happen. If so, reduce indicator history (`count` in `broker.get_candles`). |

## Useful one-liners

```bash
sudo systemctl restart hyperliquid-agent        # restart bot
journalctl -u hyperliquid-agent -f              # follow service logs
tail -f logs/agent.log                          # follow app logs
sqlite3 data/trades.db '.tables'                # inspect DB
sqlite3 data/trades.db 'select * from account;' # quick balance check
sqlite3 data/trades.db 'select count(*) from decisions;'
curl localhost:8000/account | jq
```

## Nuke + rebuild the paper state (dev only)

```bash
sudo systemctl stop hyperliquid-agent
rm data/trades.db
rm -rf data/llm_logs/*
sudo systemctl start hyperliquid-agent
```
