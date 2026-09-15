param(
    [ValidateRange(1, 24)]
    [int]$WaitHours = 12
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$candidateTests = Join-Path $root "runs\blind_qasper_seed20260822\candidate_test_results.json"
$devScript = Join-Path $root "run_dev_ab.ps1"

if (-not (Test-Path -LiteralPath $devScript)) {
    throw "Required path is missing: $devScript"
}

if (-not ("QasperWaitThenDevPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class QasperWaitThenDevPowerGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
}

$continuous = [Convert]::ToUInt32("80000000", 16)
$systemRequired = [Convert]::ToUInt32("00000001", 16)
$deadline = (Get-Date).AddHours($WaitHours)

try {
    [void][QasperWaitThenDevPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    while (-not (Test-Path -LiteralPath $candidateTests)) {
        if ((Get-Date) -ge $deadline) {
            throw "Timed out waiting for train/tool generation after $WaitHours hours. Check the first terminal."
        }
        Write-Host "[Waiting] Train analysis/tool generation is not complete. Checking again in 30 seconds..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 30
    }

    $tests = Get-Content -LiteralPath $candidateTests -Raw | ConvertFrom-Json
    if (($tests | Measure-Object).Count -lt 1) {
        throw "Candidate test result is empty; dev A/B will not start."
    }
    $failed = @($tests | Where-Object { -not $_.passed })
    if ($failed.Count -gt 0) {
        throw "Candidate self-tests contain failures; dev A/B will not start."
    }

    Write-Host "[Ready] Candidate exists and passed self-tests. Starting strict dev-20 A/B." -ForegroundColor Green
    & $devScript
}
finally {
    [void][QasperWaitThenDevPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
