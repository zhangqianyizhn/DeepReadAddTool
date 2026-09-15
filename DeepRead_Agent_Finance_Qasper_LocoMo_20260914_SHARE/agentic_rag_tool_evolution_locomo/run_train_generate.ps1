param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$prepareSplits = Join-Path $root "scripts\prepare_splits.py"
$prepareInventory = Join-Path $root "scripts\prepare_inventory.py"
$train = Join-Path $root "scripts\train_generate.py"

foreach ($required in @($python, $prepareSplits, $prepareInventory, $train)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path is missing: $required" }
}

if (-not ("LocomoSingleToolPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class LocomoSingleToolPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
}

$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

try {
    [void][LocomoSingleToolPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python $prepareSplits
    if ($LASTEXITCODE -ne 0) { throw "LocoMo split preparation failed." }
    & $python $prepareInventory
    if ($LASTEXITCODE -ne 0) { throw "LocoMo canonical inventory preparation failed." }
    if ($DryRun) {
        & $python $train --dry-run
    } else {
        & $python $train
    }
    if ($LASTEXITCODE -ne 0) {
        throw "LocoMo train baseline/tool generation failed. Send the last 30 lines, never .env."
    }
}
finally {
    [void][LocomoSingleToolPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}

