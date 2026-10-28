@echo off
REM Stop the instance started by the shortcut (PID recorded in logs\app.pid).
setlocal
cd /d "%~dp0"
if not exist "logs\app.pid" (
    echo No running instance found.
    exit /b 0
)
set /p APP_PID=<logs\app.pid
taskkill /PID %APP_PID% /F >nul 2>&1
if exist "logs\app.pid" del "logs\app.pid" >nul 2>&1
echo Stopped.
ping -n 2 127.0.0.1 >nul
