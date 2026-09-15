$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run_train_generate.ps1")
if ($LASTEXITCODE -ne 0) { throw "LocoMo train stage failed; frozen test was not opened." }
& (Join-Path $PSScriptRoot "run_dev_ab.ps1")
if ($LASTEXITCODE -ne 0) { throw "LocoMo initial Dev stage failed; frozen test was not opened." }
& (Join-Path $PSScriptRoot "run_dev_repair.ps1")
if ($LASTEXITCODE -ne 0) { throw "LocoMo Dev-guided repair failed; frozen test was not opened." }
& (Join-Path $PSScriptRoot "run_frozen_test.ps1")
if ($LASTEXITCODE -ne 0) { throw "LocoMo frozen test failed." }
