@echo off
REM One-click backup of data\*.json to the private repo (ElvyraXight/ai-ielts-speaking-data).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\sync-data.ps1"
if errorlevel 1 (
    echo.
    echo Backup failed. See the message above.
    pause
)
