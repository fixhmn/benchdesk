@echo off
cd /d "%~dp0"
if exist "dist\BenchDesk\BenchDesk.exe" (
    start "" "dist\BenchDesk\BenchDesk.exe" --demo
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m benchdesk --demo
) else (
    echo Install dependencies using the README first.
    pause
)
