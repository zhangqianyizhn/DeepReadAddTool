$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$workspaceRoot = Split-Path $repoRoot -Parent
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$config = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_pilot20_title_entity.yaml"
$rawData = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\data\financebench_open_source.jsonl"
$storeIndex = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\DeepRead\store_index"

foreach ($requiredPath in @($python, $runner, $config, $rawData, $storeIndex)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file or directory is missing: $requiredPath"
    }
}

$questionCount = @(Get-Content -LiteralPath $rawData | Where-Object { $_.Trim() }).Count
$corpusCount = @(Get-ChildItem -LiteralPath $storeIndex -File -Filter "*_corpus.json").Count
if ($questionCount -ne 20 -or $corpusCount -ne 20) {
    throw "Pilot20 validation failed: questions=$questionCount, corpora=$corpusCount."
}

Add-Type @"
using System.Runtime.InteropServices;
public static class DeepReadEntityPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)

try {
    [void][DeepReadEntityPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    Write-Host "Running the optimized 20-question entity-weighted title route." -ForegroundColor Cyan
    & $python $runner --config $config --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The optimized 20-question title-route run failed."
    }
    Write-Host "Optimized 20-question title-route run completed." -ForegroundColor Green
}
finally {
    [void][DeepReadEntityPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
