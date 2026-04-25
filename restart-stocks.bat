@echo off
REM jarvis — restart stocks bot (Alpaca paper, port 8001).
title jarvis-stocks restart
cls
echo ==========================================
echo   jarvis-stocks  -  restart
echo ==========================================
echo.

echo Stopping any running stocks bot on port 8001...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    echo   killing PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo.
echo Starting stocks bot...
cd /d "%~dp0"
start "" /MIN cmd /c "%~dp0start-stocks.bat"

echo.
echo Bot launched in a new minimised window.
timeout /t 5 /nobreak >nul
curl -s -f http://localhost:8001/health >nul 2>&1
if %ERRORLEVEL%==0 (
    echo [OK] Stocks bot is back up.
) else (
    echo [WAIT] Still booting. Check /health on :8001 in a few more seconds.
)
echo.
pause
