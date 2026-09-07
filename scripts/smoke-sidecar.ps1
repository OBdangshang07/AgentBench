param(
  [int]$Port = 43853,
  [string]$ExpectedManifestSha256 = "7ac7bade14f7307d24f083a3e308ec6e0459254f2e720b59335ac64677fb4f06"
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
  $backendSuite = $suites | Where-Object { $_.id -eq "63ae3873-1b1f-5ace-9742-8f85958356ff" }
  if (-not $backendSuite) {
    throw "Packaged sidecar does not expose the BACKEND ULTRA suite"
  }

  $manifest = Join-Path `
    $smokeRoot `
    "private-validators\backend-ultra-extreme\1.4.0\manifest.json"
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
  if (@($cases).Count -ne 299) {
    throw "Expected 299 packaged cases, got $(@($cases).Count)"
  }
  if ($backendSuite.case_count -ne 2 -or $backendSuite.docker_case_count -ne 2) {
    throw "Packaged BACKEND ULTRA suite metadata is invalid"
  }

  # Create only a draft in the isolated smoke database; do not start a model run.
  $draftBody = @{
    name = "Packaged version verification"
    suite_id = "4e5b33cb-bc26-5fda-a296-538caf7d0e8e"
    participants = @(@{
      model_id = "b837abb8-7384-5c62-9754-ac3a0d954b7f"
      runner_id = "2a2a9a4a-9333-5271-a48f-6f19509c9db1"
    })
  } | ConvertTo-Json -Depth 4
  $draft = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/experiments" -Method Post -ContentType "application/json" -Body $draftBody -TimeoutSec 20
  if ($draft.runtime_config_version -ne $version) {
    throw "Packaged experiment snapshot version $($draft.runtime_config_version) does not match $version"
  }

  [ordered]@{
    smoke_root = $smokeRoot
    health_version = $health.version
    experiment_snapshot_version = $draft.runtime_config_version
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
