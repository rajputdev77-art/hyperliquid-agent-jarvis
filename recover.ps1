# jarvis — one-click full recovery.
# Kills everything (bots, tunnel, keeper), waits, restarts in correct order,
# verifies all health endpoints, opens the dashboard. Safe to run anytime —
# nothing in this script is destructive to data, only to processes.

$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboardUrl = 'https://dashboard-sigma-nine-63.vercel.app'

function Banner([string]$msg) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Step([string]$msg) { Write-Host "  -> $msg" -ForegroundColor Yellow }
function OK([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

function Kill-Port([int]$port, [string]$name) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $procId = ($conn.OwningProcess | Select-Object -First 1)
        if ($procId) {
            Step "killing $name (pid $procId on :$port)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-Health([int]$port) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$port/health" -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# ---- 1. Stop everything ---------------------------------------------
Banner "STAGE 1 — stop everything"
Kill-Port 8000 'crypto bot'
Kill-Port 8001 'stocks bot'
Step "killing cloudflared"
Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Step "killing zombie powershell tunnel/watchdog jobs"
Get-WmiObject Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match 'tunnel-keeper\.ps1|watchdog\.ps1'
} | ForEach-Object {
    Step "  killing pid $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 4

# ---- 2. Start crypto bot --------------------------------------------
Banner "STAGE 2 — restart crypto bot"
Start-Process -FilePath (Join-Path $projectDir 'start.bat') -WorkingDirectory $projectDir -WindowStyle Minimized
Step "waiting for :8000 to come up..."
$ok = $false
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Health 8000) { $ok = $true; break }
}
if ($ok) { OK "crypto bot live on :8000" } else { Fail "crypto bot did not respond after 48s — check logs/agent.log" }

# ---- 3. Start stocks bot --------------------------------------------
Banner "STAGE 3 — restart stocks bot"
Start-Process -FilePath (Join-Path $projectDir 'start-stocks.bat') -WorkingDirectory $projectDir -WindowStyle Minimized
Step "waiting for :8001 to come up..."
$ok = $false
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Health 8001) { $ok = $true; break }
}
if ($ok) { OK "stocks bot live on :8001" } else { Fail "stocks bot did not respond after 48s — check logs/stocks-bot.log" }

# ---- 4. Start tunnel keeper -----------------------------------------
Banner "STAGE 4 — restart tunnel keeper"
Start-Process -FilePath (Join-Path $projectDir 'tunnel-keeper.bat') -WorkingDirectory $projectDir -WindowStyle Minimized
Step "waiting for cloudflared + first URL push (this can take ~45s)..."
Start-Sleep -Seconds 30
$cfRunning = Get-Process -Name cloudflared -ErrorAction SilentlyContinue
if ($cfRunning) { OK "cloudflared running (pid $($cfRunning.Id))" } else { Fail "cloudflared not detected" }

# ---- 5. Start watchdog ----------------------------------------------
Banner "STAGE 5 — restart watchdog"
Start-Process -FilePath (Join-Path $projectDir 'watchdog.bat') -WorkingDirectory $projectDir -WindowStyle Minimized
OK "watchdog spawned"

# ---- 6. Final summary -----------------------------------------------
Banner "RECOVERY COMPLETE"
Write-Host ""
Write-Host "  Crypto bot  : http://localhost:8000  ($(if (Test-Health 8000) {'UP'} else {'DOWN'}))"
Write-Host "  Stocks bot  : http://localhost:8001  ($(if (Test-Health 8001) {'UP'} else {'DOWN'}))"
Write-Host "  Cloudflared : $(if (Get-Process -Name cloudflared -ErrorAction SilentlyContinue) {'RUNNING'} else {'NOT RUNNING'})"
Write-Host ""
Write-Host "  Dashboard   : $dashboardUrl" -ForegroundColor Cyan
Write-Host ""
Step "opening dashboard in browser..."
Start-Process $dashboardUrl
Write-Host ""
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
