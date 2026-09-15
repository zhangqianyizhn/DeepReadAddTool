param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$prepare = Join-Path $root "scripts\prepare_splits.py"
$preparePdfs = Join-Path $root "scripts\prepare_pdf_pages.py"
$train = Join-Path $root "scripts\train_generate.py"

foreach ($required in @($python, $prepare, $preparePdfs, $train)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

& $python $prepare
if ($LASTEXITCODE -ne 0) { throw "Qasper split preparation failed." }

if ($DryRun) {
    & $python $train --dry-run
} else {
    & $python $preparePdfs
    if ($LASTEXITCODE -ne 0) { throw "Qasper PDF-page preparation failed." }
    & $python $train
}
if ($LASTEXITCODE -ne 0) {
    throw "Qasper train/tool-generation stage failed. Send the last 30 terminal lines, but never send .env."
}
