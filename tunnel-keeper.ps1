# jarvis — tunnel keeper.
# Spawns cloudflared, captures the trycloudflare URL, pushes it to the
# Vercel project's env vars, and triggers a redeploy so the dashboard
# always points at the live tunnel — even after a Cloudflare URL change
# (machine reboot, network blip, cloudflared crash).
#
# Run via:  powershell -ExecutionPolicy Bypass -File tunnel-keeper.ps1
# Or double-click tunnel-keeper.bat (which wraps this).

$ErrorActionPreference = 'Continue'   # don't swallow real errors silently
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile    = Join-Path $projectDir 'logs\tunnel-keeper.log'
$cfLog      = Join-Path $projectDir 'logs\cloudflared.log'
$cfBin      = Join-Path $projectDir 'bin\cloudflared.exe'
$dashboardDir = Join-Path $projectDir 'dashboard'
$vercelCmd  = "$env:APPDATA\npm\vercel.cmd"
if (-not (Test-Path $vercelCmd)) { $vercelCmd = "vercel" }  # fallback to PATH

New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Start-Tunnel {
    Log "starting cloudflared (logs -> $cfLog)"
    # Truncate old log so URL parser doesn't pick up a stale URL
    Set-Content -Path $cfLog -Value "" -Force
    $args = @('tunnel', '--url', 'http://localhost:8000', '--logfile', $cfLog)
    Start-Process -FilePath $cfBin -ArgumentList $args -WindowStyle Hidden -PassThru | Out-Null
}

function Get-TunnelUrl {
    if (-not (Test-Path $cfLog)) { return $null }
    $content = Get-Content $cfLog -ErrorAction SilentlyContinue
    if (-not $content) { return $null }
    foreach ($line in $content) {
        if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            return $matches[0]
        }
    }
    return $null
}

function Test-TunnelAlive([string]$url) {
    if (-not $url) { return $false }
    try {
        $r = Invoke-WebRequest -Uri "$url/health" -TimeoutSec 8 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Push-VercelEnv([string]$url) {
    Log "pushing NEXT_PUBLIC_API_URL=$url to Vercel + redeploying"
    Push-Location $dashboardDir
    try {
        # Remove old env (ignore failure if absent), add new, redeploy
        & $vercelCmd env rm NEXT_PUBLIC_API_URL production --yes 2>&1 | Out-Null
        $url | & $vercelCmd env add NEXT_PUBLIC_API_URL production 2>&1 | Out-Null
        & $vercelCmd --prod --yes 2>&1 | Out-Null
        Log "vercel redeploy done"
    } finally {
        Pop-Location
    }
}

# ---- main loop -------------------------------------------------------
# Wrap the whole loop in try/catch so transient errors (network blips,
# Vercel CLI hiccups) don't kill the keeper itself.

Log "tunnel-keeper online. project=$projectDir pid=$PID"
$lastPushedUrl = $null
$bootDelay = 15   # seconds to wait after start before first URL probe

while ($true) {
    try {
        # 1) ensure cloudflared is running
        $running = Get-Process -Name cloudflared -ErrorAction SilentlyContinue
        if (-not $running) {
            Log "cloudflared not running -> spawning"
            Start-Tunnel
            Start-Sleep -Seconds $bootDelay
        }

        # 2) read URL from log
        $url = Get-TunnelUrl

        # 3) verify it actually serves /health (catches the case where the URL
        #    is published but cloudflared has lost connectivity to the origin)
        if ($url -and (Test-TunnelAlive $url)) {
            if ($url -ne $lastPushedUrl) {
                Log "tunnel URL changed: $url"
                try {
                    Push-VercelEnv $url
                    $lastPushedUrl = $url
                } catch {
                    Log "vercel push failed: $_"
                }
            }
        } else {
            Log "tunnel not healthy (url=$url). killing + restarting"
            Get-Process -Name cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
            Start-Sleep -Seconds 3
            Start-Tunnel
            Start-Sleep -Seconds $bootDelay
        }
    } catch {
        Log "loop iteration error: $_ — continuing"
        Start-Sleep -Seconds 10
    }

    Start-Sleep -Seconds 60
}
