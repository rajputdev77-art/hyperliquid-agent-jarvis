# jarvis - install scheduled tasks that run components DIRECTLY (no .bat
# wrapper). Each task spawns one executable; Task Scheduler manages
# liveness; restart-on-failure is automatic.
#
# Why direct exec instead of .bat:
#   - .bat files spawn a cmd.exe child + a python child. When the cmd
#     terminates, the python child can be orphaned or killed by Task
#     Scheduler's process tree cleanup, depending on how the .bat exits.
#   - Direct exec means Task Scheduler is watching the actual process
#     it cares about (python.exe / cloudflared.exe).
#
# Run once with:  powershell -ExecutionPolicy Bypass -File install-services.ps1
# Uninstall:      powershell -ExecutionPolicy Bypass -File install-services.ps1 -Uninstall

param([switch]$Uninstall)

$ErrorActionPreference = 'Continue'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe  = Join-Path $projectDir '.venv\Scripts\python.exe'
$cfBin      = Join-Path $projectDir 'bin\cloudflared.exe'
$cfLog      = Join-Path $projectDir 'logs\cloudflared.log'
$ltLog      = Join-Path $projectDir 'logs\localtunnel.log'
# npx.cmd ships with Node — invoke localtunnel without a global install.
$npxCmd     = (Get-Command npx.cmd -EA SilentlyContinue).Source
if (-not $npxCmd) { $npxCmd = "$env:ProgramFiles\nodejs\npx.cmd" }
$ltSubdomain = $env:LT_SUBDOMAIN
if (-not $ltSubdomain) { $ltSubdomain = 'jarvis-trading' }

# Each task: one executable + its arguments. No shell in the chain.
$tasks = @(
    @{
        name    = 'jarvis-crypto-bot'
        cmd     = $pythonExe
        args    = "-u -m src.main"
        cwd     = $projectDir
    },
    @{
        name    = 'jarvis-stocks-bot'
        cmd     = $pythonExe
        args    = "-u -m src.main --market alpaca"
        cwd     = $projectDir
    },
    @{
        # Localtunnel: free, gives a STABLE subdomain (jarvis-trading.loca.lt)
        # that survives reboots. Cloudflare quick tunnels rotated URLs and
        # eventually rate-limited us with error 1034. Localtunnel needs no
        # account and no rotation logic.
        name    = 'jarvis-localtunnel'
        cmd     = $npxCmd
        args    = "--yes localtunnel --port 8000 --subdomain $ltSubdomain"
        cwd     = $projectDir
    },
    @{
        name    = 'jarvis-watchdog'
        cmd     = 'powershell.exe'
        args    = "-NoProfile -ExecutionPolicy Bypass -File `"$projectDir\watchdog.ps1`""
        cwd     = $projectDir
    },
    @{
        name    = 'jarvis-tunnel-keeper'
        cmd     = 'powershell.exe'
        args    = "-NoProfile -ExecutionPolicy Bypass -File `"$projectDir\tunnel-keeper.ps1`""
        cwd     = $projectDir
    }
)

if ($Uninstall) {
    foreach ($t in $tasks) {
        Write-Host "Removing $($t.name)..."
        schtasks /Delete /TN $t.name /F 2>&1 | Out-Null
    }
    $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    @('jarvis-bot.lnk','jarvis-stocks.lnk','jarvis-tunnel.lnk','jarvis-watchdog.lnk') | ForEach-Object {
        Remove-Item -Path "$startup\$_" -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Uninstalled."
    exit
}

# Sanity-check the executables
if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: $pythonExe not found. Create venv first." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $cfBin)) {
    Write-Host "ERROR: $cfBin not found." -ForegroundColor Red
    exit 1
}

# Remove old Startup folder shortcuts - they're brittle and now obsolete.
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
@('jarvis-bot.lnk','jarvis-stocks.lnk','jarvis-tunnel.lnk','jarvis-watchdog.lnk') | ForEach-Object {
    if (Test-Path "$startup\$_") {
        Write-Host "removing old startup shortcut: $_"
        Remove-Item -Path "$startup\$_" -Force -ErrorAction SilentlyContinue
    }
}

foreach ($t in $tasks) {
    $name = $t.name
    Write-Host ""
    Write-Host "Installing $name..." -ForegroundColor Cyan

    # Idempotent: delete if exists
    schtasks /Delete /TN $name /F 2>&1 | Out-Null

    # Escape the command/args for embedding in XML
    $escCmd  = [System.Security.SecurityElement]::Escape($t.cmd)
    $escArgs = [System.Security.SecurityElement]::Escape($t.args)
    $escCwd  = [System.Security.SecurityElement]::Escape($t.cwd)

    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>jarvis paper-trading agent - $name</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERDOMAIN\$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <DisallowStartOnRemoteAppSession>false</DisallowStartOnRemoteAppSession>
    <UseUnifiedSchedulingEngine>false</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escCmd</Command>
      <Arguments>$escArgs</Arguments>
      <WorkingDirectory>$escCwd</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

    $xmlPath = Join-Path $env:TEMP "$name.xml"
    [System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)

    schtasks /Create /TN $name /XML $xmlPath /F 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  installed" -ForegroundColor Green
    } else {
        Write-Host "  FAILED" -ForegroundColor Red
        schtasks /Create /TN $name /XML $xmlPath /F   # show error this time
    }
    Remove-Item -Path $xmlPath -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Starting all tasks now..." -ForegroundColor Cyan
foreach ($t in $tasks) {
    schtasks /Run /TN $t.name 2>&1 | Out-Null
    Write-Host "  started $($t.name)"
    Start-Sleep -Milliseconds 500
}

Write-Host ""
Write-Host "Done. Verify with:" -ForegroundColor Green
Write-Host "  schtasks /Query /TN jarvis-* /FO LIST"
Write-Host ""
Write-Host "Or just open the dashboard: https://dashboard-sigma-nine-63.vercel.app" -ForegroundColor Cyan
