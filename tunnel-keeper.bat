@echo off
REM jarvis — tunnel keeper. Spawns cloudflared + auto-updates Vercel
REM when the trycloudflare URL changes. Runs forever.
title jarvis tunnel-keeper
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-keeper.ps1"
