# Run the API server (127.0.0.1:8000) and the web app (localhost:5173) together. Ctrl+C stops both.
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI and breaks strings.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$dataDir = $null
foreach ($line in Get-Content (Join-Path $root '.env')) {
  if ($line -match '^\s*DATA_DIR\s*=\s*(.+?)\s*$') { $dataDir = $Matches[1] }
}
if (-not $dataDir) { throw 'DATA_DIR is missing in .env' }
if ($dataDir -match 'OneDrive') { throw "DATA_DIR must not be inside OneDrive: $dataDir" }

$py = Join-Path $dataDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "venv not found: $py" }
if (-not (Test-Path (Join-Path $root 'web\node_modules\vite'))) {
  throw 'web\node_modules is missing. Run scripts\web-deps.ps1 first.'
}

function Stop-Tree($p) {
  if ($p -and -not $p.HasExited) { & taskkill.exe /PID $p.Id /T /F | Out-Null }
}

$api = Start-Process -FilePath $py -WorkingDirectory $root -NoNewWindow -PassThru `
  -ArgumentList '-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', '8000'
$web = Start-Process -FilePath 'npm.cmd' -WorkingDirectory (Join-Path $root 'web') -NoNewWindow -PassThru `
  -ArgumentList 'run', 'dev'

Write-Host 'server: http://127.0.0.1:8000/health   web: http://localhost:5173   (Ctrl+C to stop)'
try {
  while (-not $api.HasExited -and -not $web.HasExited) { Start-Sleep -Seconds 1 }
  if ($api.HasExited) { Write-Warning "server exited with code $($api.ExitCode)" }
  if ($web.HasExited) { Write-Warning "web exited with code $($web.ExitCode)" }
}
finally {
  Stop-Tree $api
  Stop-Tree $web
}
