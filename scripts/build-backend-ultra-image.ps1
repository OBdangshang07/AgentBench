$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$imageTag = "agentbench/backend-ultra:1.0.0"
$dockerfileRoot = Join-Path $projectRoot "docker\backend-ultra"

Set-Location $projectRoot
docker build --pull -t $imageTag $dockerfileRoot
if ($LASTEXITCODE -ne 0) {
    throw "Backend Ultra Docker image build failed with exit code $LASTEXITCODE"
}

$smoke = docker run --rm --read-only --tmpfs /tmp:rw,nosuid,size=512m $imageTag `
    sh -c "python --version && postgres --version && redis-server --version"
if ($LASTEXITCODE -ne 0) {
    throw "Backend Ultra Docker image smoke test failed with exit code $LASTEXITCODE"
}

$smoke
Write-Host "Backend Ultra validator image $imageTag is ready." -ForegroundColor Green
