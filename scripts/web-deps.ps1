# Install web dependencies OUTSIDE OneDrive, then link web\node_modules with a junction.
# npm deletes the junction when it runs inside web\, so every npm install/ci must go through this script.
# Add a package:  .\scripts\web-deps.ps1 -Add 'some-package','-D some-dev-package'
# Or edit web\package.json and run with no arguments.
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI).
param([string[]]$Add = @())
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$web = Join-Path $root 'web'

$dataDir = $null
foreach ($line in Get-Content (Join-Path $root '.env')) {
  if ($line -match '^\s*DATA_DIR\s*=\s*(.+?)\s*$') { $dataDir = $Matches[1] }
}
if (-not $dataDir -or $dataDir -match 'OneDrive') { throw 'DATA_DIR is missing or inside OneDrive' }
$deps = Join-Path $dataDir 'web-deps'
New-Item -ItemType Directory -Force -Path $deps | Out-Null

Copy-Item (Join-Path $web 'package.json') $deps -Force
if (Test-Path (Join-Path $web 'package-lock.json')) { Copy-Item (Join-Path $web 'package-lock.json') $deps -Force }

Push-Location $deps
try {
  foreach ($a in $Add) { Invoke-Expression "npm install --no-audit --no-fund $a" }
  if ($Add.Count -eq 0) { npm install --no-audit --no-fund }
}
finally { Pop-Location }

Copy-Item (Join-Path $deps 'package.json') $web -Force
Copy-Item (Join-Path $deps 'package-lock.json') $web -Force

$link = Join-Path $web 'node_modules'
if (Test-Path $link) {
  $item = Get-Item $link -Force
  if (-not $item.LinkType) { throw "$link is a real folder inside OneDrive. Delete it and run again." }
}
else {
  cmd /c mklink /J "$link" (Join-Path $deps 'node_modules') | Out-Null
}
Write-Host "Done. node_modules -> $deps\node_modules"
