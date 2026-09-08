$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\frozen_test61.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("AgenticToolFrozenTestPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class AgenticToolFrozenTestPowerGuard {
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
    [void][AgenticToolFrozenTestPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python $script
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen test61 A/B did not complete. Re-run the same command to reuse completed stages; never send .env."
    }
}
finally {
    [void][AgenticToolFrozenTestPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
