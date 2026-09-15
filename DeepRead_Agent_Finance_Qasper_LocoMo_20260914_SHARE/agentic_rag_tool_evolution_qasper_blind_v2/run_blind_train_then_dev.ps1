param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$prepareSplits = Join-Path $root "scripts\prepare_splits.py"
$prepareInventory = Join-Path $root "scripts\prepare_canonical_inventory.py"
$train = Join-Path $root "scripts\train_generate.py"
$dev = Join-Path $root "scripts\dev_ab.py"

foreach ($required in @($python, $prepareSplits, $prepareInventory, $train, $dev)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("QasperBlindV2PowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class QasperBlindV2PowerGuard {
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
    [void][QasperBlindV2PowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python $prepareSplits
    if ($LASTEXITCODE -ne 0) { throw "Split preparation failed." }
    & $python $prepareInventory
    if ($LASTEXITCODE -ne 0) { throw "Canonical inventory preparation failed." }
    if ($DryRun) {
        & $python $train --dry-run
        if ($LASTEXITCODE -ne 0) { throw "Dry-run preflight failed." }
        exit 0
    }
    & $python $train
    if ($LASTEXITCODE -ne 0) {
        throw "Blind train/tool-generation failed. Send the last 30 lines, never .env."
    }
    & $python $dev
    if ($LASTEXITCODE -ne 0) {
        throw "Strict dev A/B failed. Send the last 30 lines, never .env."
    }
}
finally {
    [void][QasperBlindV2PowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
