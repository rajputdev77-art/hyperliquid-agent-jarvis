@echo off
REM jarvis — watchdog launcher. Starts the PowerShell watchdog in a minimised window.
title jarvis watchdog
cd /d "%~dp0"
echo Starting watchdog. It will ping the bot every 60s and auto-restart if down.
echo Log: logs\watchdog.log
echo.
echo This window will stay open. Close it to stop the watchdog.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1"
pause
