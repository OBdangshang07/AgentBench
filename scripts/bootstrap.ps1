$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -e ".\backend[dev]"

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpm) {
    $fallback = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
    if (-not (Test-Path $fallback)) { throw "pnpm is required" }
    $pnpm = $fallback
}
& $pnpm install
Write-Host "AgentBench development environment is ready." -ForegroundColor Green
