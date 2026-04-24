@echo off
REM jarvis — quick Cloudflare tunnel (no account needed).
REM Writes the current public URL to data\tunnel_url.txt so status.bat + docs can show it.
title jarvis tunnel
cd /d "%~dp0"
if not exist data mkdir data
echo Starting quick tunnel  ->  https://<random>.trycloudflare.com
echo Public URL will be written to data\tunnel_url.txt
echo Keep this window open. Close it to stop the tunnel.
echo.
bin\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate --logfile data\tunnel.log
pause
