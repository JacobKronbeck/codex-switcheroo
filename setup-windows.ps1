[CmdletBinding()]
param(
    [switch]$DesktopIcon,
    [switch]$NoDesktopIcon
)
$ErrorActionPreference = 'Stop'
if ($DesktopIcon -and $NoDesktopIcon) {
    throw 'Choose either -DesktopIcon or -NoDesktopIcon.'
}
Push-Location $PSScriptRoot
try {
    & py -3 -c 'import sys; assert sys.version_info >= (3, 10)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required; virtual environment creation failed.' }
    $pythonBin = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    & $pythonBin -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $pythonBin -c "import switcheroo, sys; sys.exit(int(not (switcheroo.state_root() / 'config.json').is_file()))"
    if ($LASTEXITCODE -ne 0) {
        & $pythonBin (Join-Path $PSScriptRoot 'switcheroo.py') init
        if ($LASTEXITCODE -ne 0) { throw 'Initialization failed. See README.md for explicit app path setup.' }
    }
    $includeIcon = $DesktopIcon.IsPresent
    if (-not $DesktopIcon -and -not $NoDesktopIcon) {
        $includeIcon = (Read-Host 'Create a desktop shortcut? [y/N]') -match '^(y|yes)$'
    }
    if ($includeIcon) { & (Join-Path $PSScriptRoot 'install-desktop.ps1') }
    Write-Host 'Setup complete. Start with .\switcheroo.ps1 or your optional desktop shortcut.'
} finally {
    Pop-Location
}
