# jarvis - tunnel keeper.
#
# Watches the cloudflared log for URL changes and pushes the new URL to
# Vercel + triggers a redeploy. Does NOT manage cloudflared itself - that
# is the jarvis-cloudflared scheduled task's job. Keeping these
# responsibilities separate avoids race conditions when both try to
# (re)start cloudflared.
#
# Run via:  powershell -ExecutionPolicy Bypass -File tunnel-keeper.ps1

$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile    = Join-Path $projectDir 'logs\tunnel-keeper.log'
$cfLog      = Join-Path $projectDir 'logs\cloudflared.log'
$dashboardDir = Join-Path $projectDir 'dashboard'
$vercelCmd  = "$env:APPDATA\npm\vercel.cmd"
if (-not (Test-Path $vercelCmd)) { $vercelCmd = "vercel" }

New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    try { Add-Content -Path $logFile -Value $line -ErrorAction Stop } catch { }
}

function Get-TunnelUrl {
    if (-not (Test-Path $cfLog)) { return $null }
    try {
        $content = Get-Content $cfLog -ErrorAction Stop
    } catch {
        return $null
    }
    if (-not $content) { return $null }
    # Pick the LAST URL match (cloudflared writes the URL once at boot;
    # if it restarted, we want the freshest one).
    $latest = $null
    foreach ($line in $content) {
        if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $latest = $matches[0]
        }
    }
    return $latest
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
        & $vercelCmd env rm NEXT_PUBLIC_API_URL production --yes 2>&1 | Out-Null
        $url | & $vercelCmd env add NEXT_PUBLIC_API_URL production 2>&1 | Out-Null
        & $vercelCmd --prod --yes 2>&1 | Out-Null
        Log "vercel redeploy done"
    } finally {
        Pop-Location
    }
}

# ---- main loop -------------------------------------------------------
Log "tunnel-keeper online. project=$projectDir pid=$PID"
$lastPushedUrl = $null

while ($true) {
    try {
        $url = Get-TunnelUrl
        if ($url -and (Test-TunnelAlive $url)) {
            if ($url -ne $lastPushedUrl) {
                Log "tunnel URL detected: $url (was: $lastPushedUrl)"
                try {
                    Push-VercelEnv $url
                    $lastPushedUrl = $url
                } catch {
                    Log "vercel push failed: $_"
                }
            } else {
                # heartbeat so the watchdog knows we're alive
                Log "tunnel healthy ($url)"
            }
        } else {
            Log "tunnel not healthy (url=$url) - waiting for cloudflared to recover"
        }
    } catch {
        Log "loop iteration error: $_ - continuing"
    }

    Start-Sleep -Seconds 60
}
