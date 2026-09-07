param(
  [string]$InstallRoot = "D:\AgentBench Desktop",
  [int]$Port = 43765
)

$ErrorActionPreference = "Stop"
$version = (Get-Content (Join-Path (Split-Path -Parent $PSScriptRoot) "package.json") -Raw | ConvertFrom-Json).version
$clientPath = Join-Path ([System.IO.Path]::GetFullPath($InstallRoot)) "agentbench-desktop.exe"
if (-not (Test-Path -LiteralPath $clientPath -PathType Leaf)) {
  throw "Installed client is missing: $clientPath"
}

$client = Get-Process -Name "agentbench-desktop" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $clientPath } |
  Select-Object -First 1
if (-not $client) {
  # This is the interactive desktop application the user asked to reopen.
  $client = Start-Process -FilePath $clientPath -WindowStyle Hidden -PassThru
}

$health = $null
for ($attempt = 0; $attempt -lt 80; $attempt++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2
    if ($health.version -eq $version) {
      break
    }
  }
  catch {
  }
  Start-Sleep -Milliseconds 500
}
if (-not $health -or $health.version -ne $version) {
  throw "Installed client backend did not become ready as $version"
}

$cases = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/test-cases" -TimeoutSec 90
$suites = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/suites" -TimeoutSec 90
$systemStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/system/status" -TimeoutSec 90
$suite = $suites |
  Where-Object { $_.id -eq "63ae3873-1b1f-5ace-9742-8f85958356ff" } |
  Select-Object -First 1
if (-not $suite) {
  throw "Installed client does not expose the BACKEND ULTRA suite"
}

$clientProcesses = Get-Process -Name "agentbench-desktop" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $clientPath }
$backendPath = Join-Path $InstallRoot "resources\backend\agentbench-backend-$version.exe"
$backendProcesses = Get-Process -Name "agentbench-backend-$version" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $backendPath }

[ordered]@{
  client_pid = $client.Id
  client_processes = @($clientProcesses).Count
  backend_processes = @($backendProcesses).Count
  health_version = $health.version
  database_ready = $systemStatus.database.ready
  case_count = @($cases).Count
  suite_name = $suite.name
  suite_case_count = $suite.case_count
  suite_docker_count = $suite.docker_case_count
  suite_estimated_minutes = $suite.estimated_minutes
} | ConvertTo-Json
