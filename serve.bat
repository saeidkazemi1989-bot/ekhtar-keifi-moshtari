@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found. Run run.bat first.
  pause
  exit /b 1
)

echo ============================================================
echo   Quality dashboard - 8D form editor
echo ============================================================
echo.
echo Starting the editable dashboard. Keep this window open.
".venv\Scripts\python.exe" serve.py --port 8000
pause
