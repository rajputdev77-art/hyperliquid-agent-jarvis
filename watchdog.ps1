# jarvis — watchdog. Pings /health every 60s; auto-restarts bot if it doesn't respond.
# Run with:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
# Or double-click watchdog.bat which wraps this.

$ErrorActionPreference = 'SilentlyContinue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$healthUrl = 'http://localhost:8000/health'
$startBat = Join-Path $projectDir 'start.bat'
$logFile = Join-Path $projectDir 'logs\watchdog.log'

# Ensure logs dir
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Is-BotAlive {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-Bot {
    Log "starting bot via $startBat"
    Start-Process -FilePath $startBat -WorkingDirectory $projectDir -WindowStyle Minimized
    Start-Sleep -Seconds 10
}

Log "watchdog online. project=$projectDir"
$fails = 0
while ($true) {
    if (Is-BotAlive) {
        if ($fails -gt 0) { Log "bot recovered" }
        $fails = 0
    } else {
        $fails += 1
        Log "bot unreachable (fail #$fails)"
        if ($fails -ge 2) {
            Log "triggering restart"
            # Kill whatever is on :8000
            $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
            if ($conn) {
                $pidToKill = $conn.OwningProcess | Select-Object -First 1
                if ($pidToKill) {
                    Log "killing stale pid $pidToKill"
                    Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
                }
            }
            Start-Bot
            $fails = 0
        }
    }
    Start-Sleep -Seconds 60
}
