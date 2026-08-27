param(
  [string]$InstallRoot = "D:\AgentBench Desktop",
  [int]$Port = 43765
)

$ErrorActionPreference = "Stop"
$clientPath = Join-Path ([System.IO.Path]::GetFullPath($InstallRoot)) "agentbench-desktop.exe"
if (-not (Test-Path -LiteralPath $clientPath -PathType Leaf)) {
  throw "Installed client is missing: $clientPath"
}

$client = Get-Process -Name "agentbench-desktop" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $clientPath } |
  Select-Object -First 1
if (-not $client) {
  # This is the interactive desktop application the user asked to reopen.
  $client = Start-Process -FilePath $clientPath -PassThru
}

$health = $null
for ($attempt = 0; $attempt -lt 80; $attempt++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2
    if ($health.version -eq "5.3.0") {
      break
    }
  }
  catch {
  }
  Start-Sleep -Milliseconds 500
}
if (-not $health -or $health.version -ne "5.3.0") {
  throw "Installed client backend did not become ready as 5.3.0"
}

$cases = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/test-cases" -TimeoutSec 10
$suites = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/suites" -TimeoutSec 10
$systemStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/system/status" -TimeoutSec 10
$suite = $suites |
  Where-Object { $_.id -eq "2fe1d745-83c7-5bd2-b197-f22452956aa6" } |
  Select-Object -First 1
if (-not $suite) {
  throw "Installed client does not expose the BACKEND ULTRA suite"
}

$clientProcesses = Get-Process -Name "agentbench-desktop" -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $clientPath }
$backendPath = Join-Path $InstallRoot "resources\backend\agentbench-backend-5.3.0.exe"
$backendProcesses = Get-Process -Name "agentbench-backend-5.3.0" -ErrorAction SilentlyContinue |
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
