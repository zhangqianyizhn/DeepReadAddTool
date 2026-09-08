param(
    [ValidateRange(1, 3)]
    [int]$CandidateLimit = 1,
    [switch]$DryRun,
    [switch]$ForceNewIndex
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements-pilot.txt"
$SetupStamp = Join-Path $ProjectDir ".venv\.pilot_requirements_installed"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Please send a screenshot of this error."
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[First setup] Creating an isolated Python environment..." -ForegroundColor Cyan
    & uv venv (Join-Path $ProjectDir ".venv") --python 3.14
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the Python environment." }
}

$NeedsInstall = -not (Test-Path -LiteralPath $SetupStamp)
if (-not $NeedsInstall) {
    & $VenvPython -c "import importlib.util,sys; names=['fitz','yaml','dotenv','openai','langchain_openai','volcenginesdkarkruntime']; sys.exit(0 if all(importlib.util.find_spec(n) for n in names) else 1)"
    $NeedsInstall = ($LASTEXITCODE -ne 0)
}

if ($NeedsInstall) {
    Write-Host "[First setup] Installing pilot dependencies (one time only)..." -ForegroundColor Cyan
    & uv pip install --python $VenvPython -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies." }
    New-Item -ItemType File -Path $SetupStamp -Force | Out-Null
}

$env:PYTHONUTF8 = "1"
$arguments = @(
    (Join-Path $ProjectDir "scripts\run_pilot.py"),
    "--candidate-limit", $CandidateLimit
)
if ($DryRun) { $arguments += "--dry-run" }
if ($ForceNewIndex) { $arguments += "--force-new-index" }

& $VenvPython @arguments
if ($LASTEXITCODE -ne 0) {
    throw "The pilot did not finish. Send the last 30 terminal lines, but never send .env."
}
