# tools/launch.ps1

<#
双击快捷方式时运行的启动器：
  1. 如果服务已经在跑，直接打开浏览器；
  2. 否则隐藏启动 Streamlit，等健康检查通过后再打开浏览器，并把 PID 写到 logs\app.pid。

测试用（不打开浏览器、打印状态）：powershell -File tools\launch.ps1 -Port 8599 -Test
停止服务：双击 stop-app.bat
#>

param(
    [int]$Port = 8501,
    [switch]$Test
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
$pidFile = Join-Path $logs 'app.pid'
$url = "http://127.0.0.1:$Port"

function Test-AppUp {
    param([string]$BaseUrl)
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/_stcore/health" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Show-Failure {
    param([string]$Message)
    $errLog = Join-Path $logs 'app.err.log'
    if (Test-Path $errLog) {
        Start-Process notepad.exe $errLog
    } else {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($Message, 'AI IELTS Speaking')
    }
}

if (-not (Test-Path $python)) {
    if ($Test) { Write-Output 'NO_VENV'; exit 1 }
    Show-Failure '缺少 .venv，请先双击 start.bat 安装环境。'
    exit 1
}

if (Test-AppUp $url) {
    if ($Test) { Write-Output "ALREADY_RUNNING $url"; exit 0 }
    Start-Process $url
    exit 0
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$arguments = @(
    '-m', 'streamlit', 'run', 'app.py',
    '--server.headless=true',
    "--server.port=$Port",
    '--browser.gatherUsageStats=false'
)
$process = Start-Process -FilePath $python -ArgumentList $arguments `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'app.out.log') `
    -RedirectStandardError (Join-Path $logs 'app.err.log')
$process.Id | Set-Content -Path $pidFile -Encoding ascii

$up = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-AppUp $url) { $up = $true; break }
}

if (-not $up) {
    if ($Test) { Write-Output "FAILED $url"; exit 1 }
    Show-Failure "App 在 60 秒内没有启动，详情见 logs\app.err.log。"
    exit 1
}

if ($Test) {
    Write-Output "STARTED $url pid=$($process.Id)"
    exit 0
}

Start-Process $url
exit 0
