# tools/make-shortcut.ps1
# Creates the three double-click shortcuts in the project root:
#   AI IELTS Speaking.lnk  -> tools\launch.ps1   (start hidden + open browser)
#   Stop App.lnk           -> tools\stop-app.ps1 (stop the hidden instance)
#   Backup Data.lnk        -> tools\sync-data.ps1 (push data\*.json to the private repo)
# Shortcuts are gitignored because they store absolute paths; rerun this after cloning.

$root = Split-Path -Parent $PSScriptRoot
$icon = Join-Path $root 'assets\app.ico'
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shell = New-Object -ComObject WScript.Shell

function New-AppShortcut {
    param(
        [string]$Name,
        [string]$Script,
        [string]$Description,
        [switch]$Hidden,
        [switch]$KeepOpen
    )
    $path = Join-Path $root $Name
    $scriptPath = Join-Path $root $Script
    if (-not (Test-Path $scriptPath)) { throw "missing $scriptPath" }

    $arguments = '-NoProfile -ExecutionPolicy Bypass'
    if ($Hidden) { $arguments += ' -WindowStyle Hidden' }
    if ($KeepOpen) { $arguments += ' -NoExit' }
    $arguments += ' -File "' + $scriptPath + '"'

    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $root
    if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
    $shortcut.Description = $Description
    $shortcut.Save()
    Write-Host "created: $path"
}

New-AppShortcut -Name 'AI IELTS Speaking.lnk' -Script 'tools\launch.ps1' -Description 'AI IELTS Speaking' -Hidden
New-AppShortcut -Name 'Stop App.lnk' -Script 'tools\stop-app.ps1' -Description 'Stop AI IELTS Speaking' -Hidden
New-AppShortcut -Name 'Backup Data.lnk' -Script 'tools\sync-data.ps1' -Description 'Backup data to the private repo' -KeepOpen
