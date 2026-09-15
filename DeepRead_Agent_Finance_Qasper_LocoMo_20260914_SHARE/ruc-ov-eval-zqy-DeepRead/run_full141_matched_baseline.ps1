$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$workspaceRoot = Split-Path $repoRoot -Parent
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$config = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_full141_matched_baseline.yaml"
$rawData = Join-Path $workspaceRoot "Data\FinanceBench\data\financebench_open_source.jsonl"
$storeIndex = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\full141\DeepRead\store_index"

foreach ($requiredPath in @($python, $runner, $config, $rawData, $storeIndex)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file or directory is missing: $requiredPath"
    }
}

$rows = @(Get-Content -LiteralPath $rawData | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$corpusCount = @(Get-ChildItem -LiteralPath $storeIndex -File -Filter "*_corpus.json").Count
if ($rows.Count -ne 141 -or @($rows | Select-Object -ExpandProperty doc_name -Unique).Count -ne 82 -or $corpusCount -ne 82) {
    throw "Full141 validation failed."
}

Add-Type @"
using System.Runtime.InteropServices;
public static class DeepReadMatchedBaselinePowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)

try {
    [void][DeepReadMatchedBaselinePowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    Write-Host "Running the configuration-matched 141-question baseline." -ForegroundColor Cyan
    & $python $runner --config $config --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The matched 141-question baseline did not complete."
    }
    Write-Host "Matched 141-question baseline completed." -ForegroundColor Green
}
finally {
    [void][DeepReadMatchedBaselinePowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
