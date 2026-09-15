$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$workspace = Split-Path $root -Parent
$python = Join-Path $workspace "agentic_rag_self_learning\.venv\Scripts\python.exe"
$script = Join-Path $root "scripts\dev_ab.py"

if (-not (Test-Path -LiteralPath $python)) { throw "Python missing: $python" }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
& $python $script
if ($LASTEXITCODE -ne 0) { throw "LocoMo one-shot Dev A/B failed. Send last 30 lines, never .env." }
