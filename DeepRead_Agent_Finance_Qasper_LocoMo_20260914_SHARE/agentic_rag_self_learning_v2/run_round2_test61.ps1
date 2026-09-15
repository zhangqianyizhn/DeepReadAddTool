$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\round2.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("Content2Round2TestPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class Content2Round2TestPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
}
$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

try {
    [void][Content2Round2TestPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    & $python $script test
    if ($LASTEXITCODE -ne 0) { throw "Content 2 Round 2 test did not complete." }
}
finally {
    [void][Content2Round2TestPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}

