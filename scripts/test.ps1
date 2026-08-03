$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
& ".venv\Scripts\python.exe" -m ruff check backend
if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE" }
& ".venv\Scripts\python.exe" -m pytest backend
if ($LASTEXITCODE -ne 0) { throw "Pytest failed with exit code $LASTEXITCODE" }

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    $node = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
}
& $node ".\node_modules\vitest\vitest.mjs" run
if ($LASTEXITCODE -ne 0) { throw "Vitest failed with exit code $LASTEXITCODE" }
& $node ".\node_modules\typescript\bin\tsc" -b
if ($LASTEXITCODE -ne 0) { throw "TypeScript build failed with exit code $LASTEXITCODE" }
Write-Host "All AgentBench checks passed." -ForegroundColor Green
