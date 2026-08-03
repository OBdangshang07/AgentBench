$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    $node = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
}
& $node ".\node_modules\@tauri-apps\cli\tauri.js" dev
