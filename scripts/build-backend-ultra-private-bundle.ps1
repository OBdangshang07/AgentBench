$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot "backend\agentbench\private_validator_sources\backend-ultra-extreme"
$bundleRoot = Join-Path $projectRoot "backend\agentbench\private_validator_bundles"
$bundlePath = Join-Path $bundleRoot "backend-ultra-extreme-1.0.2.abpv"

$requiredFiles = [ordered]@{
    ledger = @("reference_ledger.py", "reference_app.py", "validate_ledger.py")
    queue = @("reference_task_queue.py", "reference_app.py", "validate_queue.py")
}

foreach ($validatorId in $requiredFiles.Keys) {
    foreach ($fileName in $requiredFiles[$validatorId]) {
        $sourcePath = Join-Path (Join-Path $sourceRoot $validatorId) $fileName
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Missing private validator source: $sourcePath"
        }
    }
}

function Get-ValidatorFiles([string] $validatorId) {
    $result = [ordered]@{}
    foreach ($fileName in $requiredFiles[$validatorId]) {
        $sourcePath = Join-Path (Join-Path $sourceRoot $validatorId) $fileName
        $archivePath = "$validatorId/$fileName"
        $result[$archivePath] = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $result
}

$manifest = [ordered]@{
    schema_version = 1
    bundle_id = "backend-ultra-extreme"
    version = "1.0.2"
    validators = [ordered]@{
        "financial-ledger" = [ordered]@{
            command = "python {private_root}/ledger/validate_ledger.py --seed {validation_seed}"
            files = Get-ValidatorFiles "ledger"
        }
        "distributed-task-queue" = [ordered]@{
            command = "python {private_root}/queue/validate_queue.py --seed {validation_seed}"
            files = Get-ValidatorFiles "queue"
        }
    }
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
$manifestBytes = $utf8.GetBytes(($manifest | ConvertTo-Json -Depth 8 -Compress))
New-Item -ItemType Directory -Force -Path $bundleRoot | Out-Null

Add-Type -AssemblyName System.IO.Compression
$stream = [System.IO.File]::Open($bundlePath, [System.IO.FileMode]::Create)
try {
    $archive = [System.IO.Compression.ZipArchive]::new(
        $stream,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $false
    )
    try {
        $manifestEntry = $archive.CreateEntry("manifest.json")
        $manifestStream = $manifestEntry.Open()
        try {
            $manifestStream.Write($manifestBytes, 0, $manifestBytes.Length)
        }
        finally {
            $manifestStream.Dispose()
        }

        foreach ($validatorId in $requiredFiles.Keys) {
            foreach ($fileName in $requiredFiles[$validatorId]) {
                $sourcePath = Join-Path (Join-Path $sourceRoot $validatorId) $fileName
                $entry = $archive.CreateEntry("$validatorId/$fileName")
                $entryStream = $entry.Open()
                $sourceStream = [System.IO.File]::OpenRead($sourcePath)
                try {
                    $sourceStream.CopyTo($entryStream)
                }
                finally {
                    $sourceStream.Dispose()
                    $entryStream.Dispose()
                }
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    $stream.Dispose()
}

$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $sha = $sha256.ComputeHash($manifestBytes)
}
finally {
    $sha256.Dispose()
}
$manifestHash = ([System.BitConverter]::ToString($sha) -replace "-", "").ToLowerInvariant()
Write-Host "Private validator bundle: $bundlePath" -ForegroundColor Green
Write-Host "Manifest SHA-256: $manifestHash" -ForegroundColor Green
