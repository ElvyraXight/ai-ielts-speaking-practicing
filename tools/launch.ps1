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

function Test-PortOpen {
    # 不依赖 Get-NetTCPConnection（某些精简系统没有这个 cmdlet）。
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return ($task.Wait(400) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
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

# 端口有服务、但对健康检查没有响应：多半是别的程序占着。
# 这时候 Streamlit 起不来，健康检查也可能命中那个程序，于是"启动成功"却打开了别人的页面。
if (Test-PortOpen $Port) {
    if ($Test) { Write-Output "PORT_BUSY $Port"; exit 1 }
    Show-Failure "端口 $Port 已被其他程序占用（不是本 App）。请先关闭它，或用 -Port 换一个端口。"
    exit 1
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
$exitedEarly = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { $exitedEarly = $true; break }
    if (Test-AppUp $url) { $up = $true; break }
}

if (-not $up) {
    if ($Test) {
        if ($exitedEarly) { Write-Output "EXITED $url" } else { Write-Output "FAILED $url" }
        exit 1
    }
    if ($exitedEarly) {
        Show-Failure "App 启动后立刻退出了，端口 $Port 可能被占用，或依赖/配置有问题。详情见 logs\app.err.log。"
    } else {
        Show-Failure "App 在 60 秒内没有启动，详情见 logs\app.err.log。"
    }
    exit 1
}

if ($Test) {
    Write-Output "STARTED $url pid=$($process.Id)"
    exit 0
}

Start-Process $url
exit 0
