$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$trainScript = Join-Path $root "run_train_generate.ps1"
$devScript = Join-Path $root "run_dev_ab.ps1"

foreach ($required in @($trainScript, $devScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

if (-not ("QasperPdfThenDevPowerGuard" -as [type])) {
Add-Type @"
using System.Runtime.InteropServices;
public static class QasperPdfThenDevPowerGuard {
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
    [void][QasperPdfThenDevPowerGuard]::SetThreadExecutionState($continuous -bor $systemRequired)
    Write-Host "[Stage 1] Prepare paper PDFs, reuse train results, and resume AI tool generation." -ForegroundColor Cyan
    & $trainScript
    Write-Host "[Stage 2] Candidate passed self-tests. Starting strict dev-20 A/B." -ForegroundColor Cyan
    & $devScript
}
finally {
    [void][QasperPdfThenDevPowerGuard]::SetThreadExecutionState($continuous)
    Write-Host "Normal Windows sleep behavior has been restored." -ForegroundColor DarkGray
}
