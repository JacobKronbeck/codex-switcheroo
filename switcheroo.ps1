$ErrorActionPreference = 'Stop'
$pythonBin = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonBin)) {
    Write-Error 'First run: py -3 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}
& $pythonBin (Join-Path $PSScriptRoot 'switcheroo.py') @args
exit $LASTEXITCODE
