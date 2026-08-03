$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

& "$PSScriptRoot\test.ps1"
& "$PSScriptRoot\build-sidecar.ps1"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    $node = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
}
& $node ".\node_modules\@tauri-apps\cli\tauri.js" build --bundles nsis
if ($LASTEXITCODE -ne 0) {
    throw "Tauri NSIS build failed with exit code $LASTEXITCODE"
}
