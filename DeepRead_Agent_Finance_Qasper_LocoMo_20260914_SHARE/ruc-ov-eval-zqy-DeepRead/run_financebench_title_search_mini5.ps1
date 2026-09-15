$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$config = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_title_search_guarded_mini5.yaml"

foreach ($requiredPath in @($python, $runner, $config)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file is missing: $requiredPath"
    }
}

Write-Host "Running guarded 5-question title and structure routing experiment." -ForegroundColor Cyan
& $python $runner --config $config --step all --skip-ingest
if ($LASTEXITCODE -ne 0) {
    throw "Lightweight title-search run failed with exit code $LASTEXITCODE."
}

Write-Host "Guarded title-search mini run completed." -ForegroundColor Green
