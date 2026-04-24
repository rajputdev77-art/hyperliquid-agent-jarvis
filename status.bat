@echo off
REM jarvis — one-click status check. Double-click to run.
title jarvis status
cls
echo ==========================================
echo   jarvis paper-trading bot  -  status
echo ==========================================
echo.

REM 1. Is the API responding?
curl -s -f http://localhost:8000/health >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [OK] Bot is running  http://localhost:8000
    echo.
    echo ---- account ----
    curl -s http://localhost:8000/account
    echo.
    echo.
    echo ---- open positions ----
    curl -s http://localhost:8000/positions
    echo.
    echo.
    echo Opening dashboard in your browser...
    start "" http://localhost:3000
    start "" http://localhost:8000/account
) else (
    echo [DOWN] Bot not responding on http://localhost:8000
    echo.
    echo To start it: double-click start.bat
    echo To auto-restart on failure: run watchdog.bat in background
)

echo.
pause
