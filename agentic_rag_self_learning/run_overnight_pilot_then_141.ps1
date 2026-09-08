param(
    [ValidateRange(1, 3)]
    [int]$CandidateLimit = 1,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not ("PilotSleepKeeper" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class PilotSleepKeeper {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
}

$ES_CONTINUOUS = [Convert]::ToUInt32("80000000", 16)
$ES_SYSTEM_REQUIRED = [uint32]0x00000001

try {
    [PilotSleepKeeper]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null
    Write-Host "[Overnight] Automatic system sleep is temporarily disabled." -ForegroundColor Cyan

    if ($CheckOnly) {
        Write-Host "[Overnight] Sleep-control check passed; no experiment was started." -ForegroundColor Green
        return
    }

    $CompletedPilot = Get-ChildItem -LiteralPath (Join-Path $ProjectDir "runs") -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "pilot_*" -and (Test-Path -LiteralPath (Join-Path $_.FullName "RESULT_SUMMARY.md")) } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($CompletedPilot) {
        Write-Host "[Overnight] Completed pilot found; skipping all 20-question runs: $($CompletedPilot.Name)" -ForegroundColor Cyan
    }
    else {
        & (Join-Path $ProjectDir "run_pilot.ps1") -CandidateLimit $CandidateLimit
        if ($LASTEXITCODE -ne 0) { throw "The 20-question pilot did not complete." }
    }

    Write-Host "[Overnight] Pilot complete. Starting optimized 141-question run..." -ForegroundColor Cyan
    & $VenvPython (Join-Path $ProjectDir "scripts\run_full141.py")
    if ($LASTEXITCODE -ne 0) { throw "The 141-question run did not complete." }

    Write-Host "[Overnight] All requested work is complete." -ForegroundColor Green
}
finally {
    [PilotSleepKeeper]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
    Write-Host "[Overnight] Normal Windows sleep behavior has been restored." -ForegroundColor Cyan
}
