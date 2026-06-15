@echo off
REM Install jarvis components as Windows scheduled tasks (auto-restart, hidden).
REM Run this ONCE. After that, everything auto-launches at login and self-heals.
title jarvis - install services
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-services.ps1"
echo.
echo Done. Press any key to close...
pause >nul
