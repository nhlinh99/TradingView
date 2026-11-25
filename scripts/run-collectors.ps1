# Run the live collectors (trades + order book) and restart either one if it exits.
# Ctrl+C stops both. Logs: <DATA_DIR>\logs\<name>-<timestamp>.log (INFO and above).
# Symbols: pass -Symbols 'BTCUSDT,XAUUSDT' (default). They must exist in config\symbols.toml.
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI).
param([string]$Symbols = 'BTCUSDT,XAUUSDT', [switch]$SkipCatchup)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

# Only one instance at a time: a scheduled task and a manual start must not both write the same data.
# The script runs inside the calling PowerShell process, so the lock must be released in `finally` (Ctrl+C);
# otherwise it stays held by that console window and every later run there would exit. An abandoned lock
# (holder died without releasing) counts as free.
$script:mutex = New-Object System.Threading.Mutex($false, 'Global\TradingViewCollectors')
try { $owned = $script:mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) {
  $script:mutex.Dispose()
  Write-Host 'collectors already running (another run-collectors.ps1 holds the lock); exiting'; exit 0
}

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
  alerts = @('-m', 'collector.alerts')
  hotmerge = @('-m', 'collector.hotmerge')
  vnbook = @('-m', 'collector.vn_book')   # tu dong chi ghi trong gio giao dich HOSE
}
$procs = @{}

# Catch-up crawl on every start, in the background so the live collectors start at once.
# collector.daily = 1-minute candles, last 3 days of archive data (fixes gaps from the time the
# collectors were not running), VN100 candles, compaction. Safe to run while collectors write.
# -SkipCatchup turns it off. Log: <DATA_DIR>\logs\catchup-<timestamp>.log
$catchup = $null
if (-not $SkipCatchup) {
  $clog = Join-Path $logs ("catchup-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")
  $catchup = Start-Process -FilePath $py -WorkingDirectory $root -NoNewWindow -PassThru -RedirectStandardError $clog `
    -ArgumentList '-m', 'collector.daily', '--symbols', $Symbols, '--vn'
  Write-Host "started catch-up (pid $($catchup.Id)), log $clog"
}

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
  if ($catchup -and -not $catchup.HasExited) { & taskkill.exe /PID $catchup.Id /T /F | Out-Null }
  foreach ($p in $procs.Values) {
    if ($p -and -not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null }
  }
  try { $script:mutex.ReleaseMutex() } catch {}
  $script:mutex.Dispose()
}
