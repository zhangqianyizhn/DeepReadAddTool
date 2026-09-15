$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$round2 = Join-Path $root "run_round2.ps1"
$test61 = Join-Path $root "run_round2_test61.ps1"
$frozenSkill = Join-Path $root "runs\round2\frozen_skill.json"

foreach ($required in @($round2, $test61)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required script is missing: $required"
    }
}

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host "[Overnight 1/2] Running Round 2 development-set learning and gating." -ForegroundColor Cyan
& $round2

if (-not (Test-Path -LiteralPath $frozenSkill)) {
    Write-Host "[Overnight stopped safely] No Round 2 candidate passed every development-set gate. The 61-question test set remains unopened." -ForegroundColor Yellow
    exit 0
}

Write-Host "[Overnight 2/2] A candidate passed and is now frozen. Running the one-time 61-question held-out test." -ForegroundColor Cyan
& $test61
Write-Host "[Overnight completed] Round 2 and the conditional held-out test finished." -ForegroundColor Green

