$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$envFile = Join-Path $repoRoot "ov_test\.env"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$offConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_title_ab_off_mini5.yaml"
$onConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_title_ab_on_mini5.yaml"
$outputRoot = Join-Path (Split-Path $repoRoot -Parent) "ExperimentArtifacts\FinanceBenchSmoke5\Output"

foreach ($requiredPath in @($envFile, $python, $runner, $offConfig, $onConfig)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file is missing: $requiredPath"
    }
}

$envText = Get-Content -LiteralPath $envFile -Raw
if ($envText -match "VOLCANO_API_KEY\s*=\s*(paste-your-volcengine-api-key-here)?\s*(?:`r?`n|$)") {
    throw "Edit ov_test\.env and replace VOLCANO_API_KEY with your real Volcengine Ark API key."
}

Write-Host "[1/2] Running OFF baseline: indexing 5 documents and answering 5 questions." -ForegroundColor Cyan
& $python $runner --config $offConfig --step all
if ($LASTEXITCODE -ne 0) {
    throw "OFF run failed with exit code $LASTEXITCODE. The ON run was not started."
}

Write-Host "[2/2] Running ON title-preload variant using the same index." -ForegroundColor Cyan
& $python $runner --config $onConfig --step all --skip-ingest
if ($LASTEXITCODE -ne 0) {
    throw "ON run failed with exit code $LASTEXITCODE."
}

Write-Host "Both mini smoke runs completed. Output directory:" -ForegroundColor Green
Write-Host $outputRoot
if (Test-Path -LiteralPath $outputRoot) {
    Get-ChildItem -LiteralPath $outputRoot -Directory |
        Sort-Object LastWriteTime |
        Select-Object Name, LastWriteTime
}
