# tools/stop-app.ps1
# Stop the instance started by launch.ps1 (PID recorded in logs\app.pid).

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'logs\app.pid'

if (-not (Test-Path $pidFile)) { exit 0 }

$appPid = Get-Content $pidFile | Select-Object -First 1
if ($appPid) { Stop-Process -Id ([int]$appPid) -Force -ErrorAction SilentlyContinue }
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
