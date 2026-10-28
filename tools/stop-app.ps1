# tools/stop-app.ps1
# Stop the instance started by launch.ps1 (PID recorded in logs\app.pid).

$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root 'logs\app.pid'

if (-not (Test-Path $pidFile)) { exit 0 }

$appPid = Get-Content $pidFile | Select-Object -First 1
if ($appPid) {
    # /T 结束整棵进程树：launch.ps1 记录的 pid 是它启动的那个进程，
    # Streamlit 真正监听端口的是它的子进程；只杀父进程会留下占着端口的孤儿。
    & taskkill.exe /PID ([int]$appPid) /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id ([int]$appPid) -Force -ErrorAction SilentlyContinue
    }
}
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
