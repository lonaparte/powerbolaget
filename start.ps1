$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$coastalPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $coastalPython)) { $coastalPython = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $coastalPython)) { $coastalPython = 'python' }
& $coastalPython run.py
