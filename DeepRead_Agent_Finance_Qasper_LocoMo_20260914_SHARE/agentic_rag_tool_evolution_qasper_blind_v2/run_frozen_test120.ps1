$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\frozen_test120.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("QasperBlindV2FrozenTestPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class QasperBlindV2FrozenTestPowerGuard {
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
    [void][QasperBlindV2FrozenTestPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python $script
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen Qasper test120 did not complete. Send the last 30 terminal lines, but never send .env."
    }
}
finally {
    [void][QasperBlindV2FrozenTestPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
