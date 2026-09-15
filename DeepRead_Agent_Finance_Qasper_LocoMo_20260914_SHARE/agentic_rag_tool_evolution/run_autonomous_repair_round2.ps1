param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\repair_round2.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("AgenticToolRepairRound2PowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class AgenticToolRepairRound2PowerGuard {
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

$arguments = @($script)
if ($DryRun) { $arguments += "--dry-run" }

try {
    [void][AgenticToolRepairRound2PowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Autonomous repair Round 2 did not complete. Send the last 30 terminal lines, but never send .env."
    }
}
finally {
    [void][AgenticToolRepairRound2PowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
