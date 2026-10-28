# tools/make-shortcut.ps1
# Creates "AI IELTS Speaking.lnk" in the project root, pointing at tools\launch.ps1.
# Run once after cloning (the .lnk itself is gitignored because it stores absolute paths).

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'tools\launch.ps1'
$icon = Join-Path $root 'assets\app.ico'
$target = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcutPath = Join-Path $root 'AI IELTS Speaking.lnk'

if (-not (Test-Path $launcher)) { throw "missing $launcher" }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$shortcut.WorkingDirectory = $root
if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
$shortcut.Description = 'AI IELTS Speaking'
$shortcut.Save()

Write-Host "created: $shortcutPath"
