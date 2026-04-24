@echo off
REM jarvis — auto-start launcher for Windows.
REM Drop a shortcut to this file into shell:startup to run on every login.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo [jarvis] .venv missing. Create it first: py -3.13 -m venv .venv
    pause
    exit /b 1
)
if not exist .env (
    echo [jarvis] .env missing. Copy .env.example to .env and fill GEMINI_API_KEY.
    pause
    exit /b 1
)
echo [jarvis] starting paper-trading bot + API on :8000 ...
.venv\Scripts\python.exe -m src.main
pause
