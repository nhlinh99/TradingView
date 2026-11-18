# Register (or remove) the Windows scheduled tasks that keep the collectors running.
#   .\scripts\install-tasks.ps1            install both tasks (current user, no admin needed)
#   .\scripts\install-tasks.ps1 -Remove    delete them
# Tasks:
#   TradingView-Collectors  at logon: run-collectors.ps1 (trades, order book, Deribit, alerts, hotmerge, VN order book)
#   TradingView-Daily       every day 03:00: collector.daily --vn (candles, archive gap fill, VN100 candles, compaction)
# A missed run starts as soon as the PC is on again. run-collectors.ps1 refuses to start a second copy.
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI).
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$names = @('TradingView-Collectors', 'TradingView-Daily')

if ($Remove) {
  foreach ($n in $names) {
    if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $n -Confirm:$false; Write-Host "removed $n" }
  }
  return
}

$dataDir = $null
foreach ($line in Get-Content (Join-Path $root '.env')) {
  if ($line -match '^\s*DATA_DIR\s*=\s*(.+?)\s*$') { $dataDir = $Matches[1] }
}
if (-not $dataDir -or $dataDir -match 'OneDrive') { throw 'DATA_DIR is missing or inside OneDrive' }
$py = Join-Path $dataDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv not found: $py" }

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

$collect = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
  -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $root 'scripts\run-collectors.ps1') + '"')
Register-ScheduledTask -TaskName $names[0] -Action $collect -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) `
  -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "registered $($names[0]) (at logon)"

$daily = New-ScheduledTaskAction -Execute $py -WorkingDirectory $root -Argument '-m collector.daily --vn'
Register-ScheduledTask -TaskName $names[1] -Action $daily -Trigger (New-ScheduledTaskTrigger -Daily -At '03:00') `
  -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "registered $($names[1]) (daily 03:00)"
Write-Host 'Not started now. They start at next logon / 03:00. To start the collectors now: Start-ScheduledTask -TaskName TradingView-Collectors'
