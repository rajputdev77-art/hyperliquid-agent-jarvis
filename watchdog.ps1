# jarvis - watchdog. Pings /health every 60s; auto-restarts bot if it doesn't respond.
# Run with:  powershell -ExecutionPolicy Bypass -File watchdog.ps1
# Or double-click watchdog.bat which wraps this.

$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $projectDir 'logs\watchdog.log'

# Singleton check: only one watchdog at a time.
$me = $PID
$others = Get-WmiObject Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -match 'watchdog\.ps1' -and $_.ProcessId -ne $me }
if ($others) {
    Write-Host "another watchdog is already running (pids: $(($others | ForEach-Object ProcessId) -join ','))"
    exit 0
}

# Bots monitored: name, port, launcher script.
$bots = @(
    @{ name = 'crypto'; port = 8000; launcher = 'start.bat'        },
    @{ name = 'stocks'; port = 8001; launcher = 'start-stocks.bat' }
)

New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    try { Add-Content -Path $logFile -Value $line -ErrorAction Stop } catch { }
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

function Test-TunnelKeeperAlive {
    # Watchdog should leave the keeper alone if jarvis-tunnel-keeper task
    # is running OR a powershell process running tunnel-keeper.ps1 exists.
    # Don't trust log mtime alone - if multiple keepers race for the log
    # file, the mtime can stay old while keepers pile up.
    try {
        $taskState = (schtasks /Query /TN jarvis-tunnel-keeper /FO LIST 2>&1) -join "`n"
        if ($taskState -match 'Status:\s+Running') { return $true }
    } catch { }
    $procs = Get-WmiObject Win32_Process -Filter "Name = 'powershell.exe'" -EA SilentlyContinue |
             Where-Object { $_.CommandLine -match 'tunnel-keeper\.ps1' }
    return ($procs.Count -gt 0)
}

function Start-TunnelKeeper {
    # Use the scheduled task instead of spawning a fresh PS process.
    # That way Task Scheduler owns the keeper's lifecycle and we don't
    # accidentally run multiple keepers in parallel.
    Log "[tunnel-keeper] kicking scheduled task"
    schtasks /Run /TN jarvis-tunnel-keeper 2>&1 | Out-Null
    Start-Sleep -Seconds 15
}

Log "watchdog online. project=$projectDir bots=$($bots.Count) + tunnel-keeper"
$failCounters = @{}
foreach ($b in $bots) { $failCounters[$b.name] = 0 }
$failCounters['tunnel-keeper'] = 0

while ($true) {
    try {
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

        # Tunnel-keeper liveness check
        if (Test-TunnelKeeperAlive) {
            if ($failCounters['tunnel-keeper'] -gt 0) { Log "[tunnel-keeper] recovered" }
            $failCounters['tunnel-keeper'] = 0
        } else {
            $failCounters['tunnel-keeper'] += 1
            Log "[tunnel-keeper] log stale (fail #$($failCounters['tunnel-keeper']))"
            if ($failCounters['tunnel-keeper'] -ge 2) {
                Log "[tunnel-keeper] triggering restart"
                Start-TunnelKeeper
                $failCounters['tunnel-keeper'] = 0
            }
        }
    } catch {
        Log "watchdog loop error: $_ - continuing"
    }
    Start-Sleep -Seconds 60
}
