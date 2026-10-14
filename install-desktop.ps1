# Create a per-user shortcut; the target runs in its own console window.
$ErrorActionPreference = 'Stop'
$pythonBin = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonBin)) {
    throw 'Run setup-windows.ps1 before installing the desktop shortcut.'
}
$desktopPath = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktopPath) { throw 'Windows did not report a Desktop folder.' }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktopPath 'Codex Switcheroo.lnk'))
$shortcut.TargetPath = $pythonBin
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'switcheroo.py') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Open the Codex Switcheroo account picker'
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,0"
$shortcut.Save()
Write-Host "Installed desktop shortcut in $desktopPath"
