param(
    [switch]$DryRun,
    [ValidateRange(6, 30)]
    [int]$FailureCases = 16,
    [ValidateRange(0, 10)]
    [int]$SuccessCases = 4
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\blind_reconstruction.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$arguments = @(
    $script,
    "--failure-cases", $FailureCases,
    "--success-cases", $SuccessCases
)
if ($DryRun) { $arguments += "--dry-run" }

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Blind reconstruction did not complete. Send the last 30 terminal lines, but never send .env."
}
