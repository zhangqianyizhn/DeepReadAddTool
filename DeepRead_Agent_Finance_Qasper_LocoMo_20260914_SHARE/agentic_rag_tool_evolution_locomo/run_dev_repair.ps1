$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\dev_repair.py"

foreach ($required in @($python, $script)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path is missing: $required" }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
& $python $script
if ($LASTEXITCODE -ne 0) {
    throw "LocoMo Dev-guided autonomous repair failed. Send last 30 lines, never .env."
}
