@echo off
REM jarvis — US stocks (Alpaca paper) launcher. Port :8001.
REM Drop a shortcut to this file into shell:startup to run on every login.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo [jarvis-stocks] .venv missing. Create it first: py -3.13 -m venv .venv
    pause
    exit /b 1
)
if not exist .env (
    echo [jarvis-stocks] .env missing. Copy .env.example to .env and fill keys.
    pause
    exit /b 1
)
echo [jarvis-stocks] starting Alpaca paper-trading bot + API on :8001 ...
.venv\Scripts\python.exe -m src.main --market alpaca
pause
