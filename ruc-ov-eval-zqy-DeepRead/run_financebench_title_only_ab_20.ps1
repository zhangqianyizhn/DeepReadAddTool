$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$workspaceRoot = Split-Path $repoRoot -Parent
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$baselineConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_pilot20_baseline.yaml"
$titleConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_pilot20_title_only.yaml"
$rawData = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\data\financebench_open_source.jsonl"
$storeIndex = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\DeepRead\store_index"

Add-Type @"
using System.Runtime.InteropServices;
public static class DeepReadPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)

foreach ($requiredPath in @($python, $runner, $baselineConfig, $titleConfig, $rawData, $storeIndex)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file or directory is missing: $requiredPath"
    }
}

$questionCount = @(Get-Content -LiteralPath $rawData | Where-Object { $_.Trim() }).Count
$corpusCount = @(Get-ChildItem -LiteralPath $storeIndex -File -Filter "*_corpus.json").Count
if ($questionCount -ne 20 -or $corpusCount -ne 20) {
    throw "Pilot20 validation failed: questions=$questionCount, corpora=$corpusCount; expected 20 and 20."
}

try {
    [void][DeepReadPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    Write-Host "Windows automatic sleep is temporarily disabled for this process." -ForegroundColor DarkGray

    Write-Host "[1/2] Running the 20-question baseline with the existing read-only index." -ForegroundColor Cyan
    & $python $runner --config $baselineConfig --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The 20-question baseline failed; title-only run was not started."
    }

    Write-Host "[2/2] Running the paired 20-question document-title routing experiment." -ForegroundColor Cyan
    & $python $runner --config $titleConfig --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The 20-question title-only run failed."
    }

    Write-Host "Both paired 20-question runs completed." -ForegroundColor Green
    Write-Host (Join-Path $workspaceRoot "ExperimentArtifacts\FinanceBenchPilot20\Output")
}
finally {
    [void][DeepReadPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
