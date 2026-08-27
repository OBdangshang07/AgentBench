param(
  [int]$Port = 43853,
  [string]$ExpectedManifestSha256 = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$version = (Get-Content ".\package.json" -Raw | ConvertFrom-Json).version
$sidecar = Join-Path $projectRoot "dist\agentbench-backend-$version.exe"
if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
  throw "Missing packaged sidecar: $sidecar"
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
  throw "Smoke port $Port is already in use"
}

$runId = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$smokeRoot = Join-Path $projectRoot ".smoke-sidecar-$version-$runId"
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
$stdout = Join-Path $smokeRoot "stdout.log"
$stderr = Join-Path $smokeRoot "stderr.log"

$env:AGENTBENCH_DATA_DIR = $smokeRoot
$env:AGENTBENCH_PORT = [string]$Port
$env:AGENTBENCH_HOST = "127.0.0.1"
$startedAt = Get-Date
$process = Start-Process `
  -FilePath $sidecar `
  -PassThru `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr

try {
  $health = $null
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
      $health = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/api/v1/health" `
        -TimeoutSec 2
      break
    }
    catch {
      Start-Sleep -Milliseconds 500
    }
  }
  if (-not $health) {
    $errorText = Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue
    throw "Sidecar did not become ready: $errorText"
  }

  $cases = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/test-cases" -TimeoutSec 10
  $suites = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/suites" -TimeoutSec 10
  $backendSuite = $suites | Where-Object { $_.id -eq "2fe1d745-83c7-5bd2-b197-f22452956aa6" }
  if (-not $backendSuite) {
    throw "Packaged sidecar does not expose the BACKEND ULTRA suite"
  }

  $manifest = Join-Path `
    $smokeRoot `
    "private-validators\backend-ultra-extreme\1.0.0\manifest.json"
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Packaged private validator manifest was not installed"
  }
  $manifestHash = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($ExpectedManifestSha256 -and $manifestHash -ne $ExpectedManifestSha256.ToLowerInvariant()) {
    throw "Private validator manifest hash mismatch: $manifestHash"
  }
  if ($health.version -ne $version) {
    throw "Health version $($health.version) does not match package version $version"
  }
  if (@($cases).Count -ne 284) {
    throw "Expected 284 packaged cases, got $(@($cases).Count)"
  }
  if ($backendSuite.case_count -ne 2 -or $backendSuite.docker_case_count -ne 2) {
    throw "Packaged BACKEND ULTRA suite metadata is invalid"
  }

  [ordered]@{
    smoke_root = $smokeRoot
    health_version = $health.version
    case_count = @($cases).Count
    suite_case_count = $backendSuite.case_count
    suite_docker_count = $backendSuite.docker_case_count
    suite_estimated_minutes = $backendSuite.estimated_minutes
    private_manifest_sha256 = $manifestHash
  } | ConvertTo-Json
}
finally {
  $processName = [System.IO.Path]::GetFileNameWithoutExtension($sidecar)
  $launchedProcesses = Get-Process -Name $processName -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Path -eq $sidecar -and $_.StartTime -ge $startedAt.AddSeconds(-1)
    }
  foreach ($launchedProcess in $launchedProcesses) {
    Stop-Process -Id $launchedProcess.Id -Force -ErrorAction SilentlyContinue
  }
  Remove-Item Env:AGENTBENCH_DATA_DIR -ErrorAction SilentlyContinue
  Remove-Item Env:AGENTBENCH_PORT -ErrorAction SilentlyContinue
  Remove-Item Env:AGENTBENCH_HOST -ErrorAction SilentlyContinue
}
