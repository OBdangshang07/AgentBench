$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$version = (Get-Content ".\package.json" -Raw | ConvertFrom-Json).version
$sidecarName = "agentbench-backend-$version"

$packagingPython = ".packaging-venv\Scripts\python.exe"
if (-not (Test-Path $packagingPython)) {
  $packagingPython = ".venv\Scripts\python.exe"
}

& $packagingPython -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name $sidecarName `
  --collect-all keyring `
  --collect-all uvicorn `
  ".\backend\agentbench_entry.py"
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Copy-Item ".\dist\$sidecarName.exe" ".\src-tauri\resources\backend\$sidecarName.exe" -Force
Write-Host "Python Sidecar $sidecarName packaged." -ForegroundColor Green
