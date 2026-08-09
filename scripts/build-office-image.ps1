$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$imageTag = "agentbench/office-validator:1.0"

# Dockerfile 内容：python:3.12-slim 基础镜像 + Office 解析三件套（固定大版本），并清理 pip 缓存
$dockerfile = @'
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "openpyxl==3.1.*" \
    "python-docx==1.*" \
    "python-pptx==1.*"

CMD ["python"]
'@

# 在临时目录生成 Dockerfile，结束后清理
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("agentbench-office-image-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    Set-Content -Path (Join-Path $tempDir "Dockerfile") -Value $dockerfile -Encoding ascii

    Set-Location $projectRoot
    Write-Host "Building Docker image $imageTag ..." -ForegroundColor Cyan
    docker build -t $imageTag $tempDir
    if ($LASTEXITCODE -ne 0) {
        throw "docker build failed with exit code $LASTEXITCODE"
    }

    Write-Host "Running smoke test (import openpyxl, docx, pptx) ..." -ForegroundColor Cyan
    $smokeOutput = docker run --rm $imageTag python -c "import openpyxl, docx, pptx; print('OK')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $smokeOutput -ForegroundColor Red
        throw "Smoke test failed with exit code $LASTEXITCODE"
    }
    if (($smokeOutput | Out-String).Trim() -ne "OK") {
        Write-Host $smokeOutput -ForegroundColor Red
        throw "Smoke test did not print OK"
    }

    Write-Host "Smoke test passed: OK" -ForegroundColor Green
    docker images --format "{{.Repository}}:{{.Tag}} {{.Size}}" | Select-String ([regex]::Escape($imageTag))
    Write-Host "Office validator image $imageTag is ready." -ForegroundColor Green
}
finally {
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
