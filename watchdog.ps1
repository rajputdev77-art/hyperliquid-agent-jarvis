# jarvis — watchdog. Pings /health every 60s; auto-restarts bot if it doesn't respond.
# Run with:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
# Or double-click watchdog.bat which wraps this.

$ErrorActionPreference = 'SilentlyContinue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $projectDir 'logs\watchdog.log'

# Bots monitored: name, port, launcher script.
$bots = @(
    @{ name = 'crypto'; port = 8000; launcher = 'start.bat'        },
    @{ name = 'stocks'; port = 8001; launcher = 'start-stocks.bat' }
)

New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Is-BotAlive([int]$port) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$port/health" -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Start-Bot([string]$name, [int]$port, [string]$launcher) {
    $bat = Join-Path $projectDir $launcher
    if (-not (Test-Path $bat)) { Log "[$name] launcher missing: $bat (skip)"; return }
    Log "[$name] starting via $launcher"
    # Kill anything stale on the port first
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pidToKill = $conn.OwningProcess | Select-Object -First 1
        if ($pidToKill) {
            Log "[$name] killing stale pid $pidToKill on :$port"
            Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Process -FilePath $bat -WorkingDirectory $projectDir -WindowStyle Minimized
    Start-Sleep -Seconds 10
}

Log "watchdog online. project=$projectDir bots=$($bots.Count)"
$failCounters = @{}
foreach ($b in $bots) { $failCounters[$b.name] = 0 }

while ($true) {
    foreach ($b in $bots) {
        $name = $b.name; $port = $b.port; $launcher = $b.launcher
        if (Is-BotAlive $port) {
            if ($failCounters[$name] -gt 0) { Log "[$name] recovered" }
            $failCounters[$name] = 0
        } else {
            $failCounters[$name] += 1
            Log "[$name] unreachable on :$port (fail #$($failCounters[$name]))"
            if ($failCounters[$name] -ge 2) {
                Log "[$name] triggering restart"
                Start-Bot $name $port $launcher
                $failCounters[$name] = 0
            }
        }
    }
    Start-Sleep -Seconds 60
}
