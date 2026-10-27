@echo off
chcp 65001 >nul

echo 正在清理语音文件...
if exist "audio_records" del /q "audio_records\*.*" 2>nul

echo.
echo 正在激活虚拟环境...
call .venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [错误] 找不到 venv 文件夹！请确认 bat 文件和 venv 在同一目录。
    pause
    exit /b
)

echo.
echo 正在启动 Streamlit...
python -m streamlit run app.py

echo.
echo ——————————————————————————
echo 程序已退出 (或崩溃)。
echo ——————————————————————————

pause