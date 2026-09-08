$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "The pilot Python environment is missing. Run run_pilot.ps1 -DryRun first."
}

if (-not ("BaselineSleepKeeper" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class BaselineSleepKeeper {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}

$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_SYSTEM_REQUIRED = [uint32]0x00000001

try {
    [BaselineSleepKeeper]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null
    Write-Host "[Baseline141] Automatic system sleep is temporarily disabled." -ForegroundColor Cyan
    & $VenvPython (Join-Path $ProjectDir "scripts\run_baseline141.py")
    if ($LASTEXITCODE -ne 0) { throw "The 141-question baseline did not complete." }
    Write-Host "[Baseline141] Baseline and paired comparison are complete." -ForegroundColor Green
}
finally {
    [BaselineSleepKeeper]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host "[Baseline141] Normal Windows sleep behavior has been restored." -ForegroundColor Cyan
}

