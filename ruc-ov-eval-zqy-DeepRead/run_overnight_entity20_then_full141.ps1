$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$workspaceRoot = Split-Path $repoRoot -Parent
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$runner = Join-Path $repoRoot "ov_test\run.py"
$pilotConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_pilot20_title_entity.yaml"
$fullConfig = Join-Path $repoRoot "ov_test\config_deepread_global\financebench_full141_title_entity.yaml"
$pilotRaw = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\data\financebench_open_source.jsonl"
$pilotIndex = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\pilot20\DeepRead\store_index"
$fullRaw = Join-Path $workspaceRoot "Data\FinanceBench\data\financebench_open_source.jsonl"
$fullIndex = Join-Path $workspaceRoot "agentic_rag_self_learning\data\generated\full141\DeepRead\store_index"
$pilotOutputRoot = Join-Path $workspaceRoot "ExperimentArtifacts\FinanceBenchPilot20\Output"
$fullOutputRoot = Join-Path $workspaceRoot "ExperimentArtifacts\FinanceBenchFull141\Output"

foreach ($requiredPath in @($python, $runner, $pilotConfig, $fullConfig, $pilotRaw, $pilotIndex, $fullRaw, $fullIndex)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file or directory is missing: $requiredPath"
    }
}

$pilotQuestions = @(Get-Content -LiteralPath $pilotRaw | Where-Object { $_.Trim() }).Count
$pilotCorpora = @(Get-ChildItem -LiteralPath $pilotIndex -File -Filter "*_corpus.json").Count
$fullRows = @(Get-Content -LiteralPath $fullRaw | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$fullQuestions = $fullRows.Count
$fullUniqueDocs = @($fullRows | Select-Object -ExpandProperty doc_name -Unique).Count
$fullCorpora = @(Get-ChildItem -LiteralPath $fullIndex -File -Filter "*_corpus.json").Count

if ($pilotQuestions -ne 20 -or $pilotCorpora -ne 20) {
    throw "Pilot validation failed: questions=$pilotQuestions, corpora=$pilotCorpora."
}
if ($fullQuestions -ne 141 -or $fullUniqueDocs -ne 82 -or $fullCorpora -ne 82) {
    throw "Full validation failed: questions=$fullQuestions, unique_docs=$fullUniqueDocs, corpora=$fullCorpora."
}

Add-Type @"
using System.Runtime.InteropServices;
public static class DeepReadOvernightPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)

try {
    [void][DeepReadOvernightPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    Write-Host "[Overnight 1/2] Running optimized 20-question validation." -ForegroundColor Cyan
    & $python $runner --config $pilotConfig --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The 20-question validation failed; the 141-question run was not started."
    }

    $pilotRun = Get-ChildItem -LiteralPath $pilotOutputRoot -Directory -Filter "deepread_title_entity_20_*" |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    if ($null -eq $pilotRun) {
        throw "Could not locate the completed 20-question output."
    }
    $pilotReportPath = Join-Path $pilotRun.FullName "benchmark_metrics_report.json"
    $pilotReport = Get-Content -LiteralPath $pilotReportPath -Raw | ConvertFrom-Json
    $pilotAccuracy = [double]$pilotReport.'Performance Metrics'.'Average Accuracy (normalization)'
    Write-Host ("20-question normalized accuracy: {0:P2}" -f $pilotAccuracy) -ForegroundColor Yellow
    if ($pilotAccuracy -lt 0.8375) {
        throw "Automatic gate stopped the full run: optimized 20-question accuracy is below the 0.8375 baseline."
    }

    Write-Host "[Overnight 2/2] Gate passed. Running all 141 questions with the existing 82-document index." -ForegroundColor Cyan
    & $python $runner --config $fullConfig --step all --skip-ingest
    if ($LASTEXITCODE -ne 0) {
        throw "The 141-question run did not complete. Completed task records remain in its output directory."
    }

    $fullRun = Get-ChildItem -LiteralPath $fullOutputRoot -Directory -Filter "deepread_title_entity_141_*" |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    $fullReportPath = Join-Path $fullRun.FullName "benchmark_metrics_report.json"
    $fullReport = Get-Content -LiteralPath $fullReportPath -Raw | ConvertFrom-Json
    $fullAccuracy = [double]$fullReport.'Performance Metrics'.'Average Accuracy (normalization)'
    $fullInput = [double]$fullReport.'Query Efficiency (Average Per Query)'.'Average Input Tokens'
    $fullSeconds = [double]$fullReport.'Query Efficiency (Average Per Query)'.'Average Retrieval Time (s)'

    Write-Host "Overnight experiment completed successfully." -ForegroundColor Green
    Write-Host ("141-question accuracy: {0:P2}" -f $fullAccuracy)
    Write-Host ("Average input tokens/question: {0:N0}" -f $fullInput)
    Write-Host ("Average retrieval time/question: {0:N1}s" -f $fullSeconds)
    Write-Host $fullRun.FullName
}
finally {
    [void][DeepReadOvernightPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
