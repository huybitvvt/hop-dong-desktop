@echo off
cd /d "%~dp0"
set "hopDongExe="
if exist "dist\current-app.txt" set /p "hopDongExe="<"dist\current-app.txt"
if defined hopDongExe (
    if exist "%hopDongExe%" (
        start "" "%hopDongExe%"
        exit /b
    )
)
if exist "dist\HopDongAI\HopDongAI.exe" (
    start "" "dist\HopDongAI\HopDongAI.exe"
    exit /b
)
if not exist ".venv\Scripts\python.exe" (
    echo Chua co moi truong Python. Hay dung ban dong goi hoac chay Setup.ps1.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
