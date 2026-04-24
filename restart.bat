@echo off
REM jarvis — one-click restart. Kills any running bot and launches a fresh one.
title jarvis restart
cls
echo ==========================================
echo   jarvis  -  restart
echo ==========================================
echo.

echo Stopping any running bot process on port 8000...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   killing PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo.
echo Starting bot...
cd /d "%~dp0"
start "" /MIN cmd /c "%~dp0start.bat"

echo.
echo Bot launched in a new minimised window.
echo Give it ~5 seconds, then run status.bat to verify.
echo.
timeout /t 5 /nobreak >nul
curl -s -f http://localhost:8000/health >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [OK] Bot is back up.
) else (
    echo [WAIT] Still booting. Run status.bat in a few more seconds.
)
echo.
pause
