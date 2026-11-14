# Run the live collectors (trades + order book) and restart either one if it exits.
# Ctrl+C stops both. Logs: <DATA_DIR>\logs\<name>-<timestamp>.log (INFO and above).
# Symbols: pass -Symbols 'BTCUSDT,XAUUSDT' (default). They must exist in config\symbols.toml.
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI).
param([string]$Symbols = 'BTCUSDT,XAUUSDT')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

$dataDir = $null
foreach ($line in Get-Content (Join-Path $root '.env')) {
  if ($line -match '^\s*DATA_DIR\s*=\s*(.+?)\s*$') { $dataDir = $Matches[1] }
}
if (-not $dataDir -or $dataDir -match 'OneDrive') { throw 'DATA_DIR is missing or inside OneDrive' }
$py = Join-Path $dataDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv not found: $py" }
$logs = Join-Path $dataDir 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$jobs = [ordered]@{
  trades = @('-m', 'collector.live_trades', '--symbols', $Symbols)
  book   = @('-m', 'collector.live_book', '--symbols', $Symbols)
  deribit = @('-m', 'collector.deribit')
}
$procs = @{}

try {
  while ($true) {
    foreach ($name in @($jobs.Keys)) {
      if (-not $procs.ContainsKey($name) -or $procs[$name].HasExited) {
        if ($procs.ContainsKey($name)) { Write-Warning "$name exited with code $($procs[$name].ExitCode), restarting" }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $log = Join-Path $logs "$name-$stamp.log"
        $procs[$name] = Start-Process -FilePath $py -ArgumentList $jobs[$name] -WorkingDirectory $root `
          -NoNewWindow -PassThru -RedirectStandardError $log
        Write-Host "started $name (pid $($procs[$name].Id)), log $log"
      }
    }
    Start-Sleep -Seconds 10
  }
}
finally {
  foreach ($p in $procs.Values) {
    if ($p -and -not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null }
  }
}
