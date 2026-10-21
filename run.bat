@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Quality Warning Classification Report - builder
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  echo         Install Python 3.10+ from https://python.org and enable "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment in .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
  )
) else (
  echo [1/3] Virtual environment found.
)

echo [2/3] Checking required packages ...
".venv\Scripts\python.exe" -c "import pandas, openpyxl, rapidfuzz, jdatetime, docx" >nul 2>nul
if errorlevel 1 (
  echo       Installing missing packages ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Package installation failed.
    echo         Check your internet connection and try again.
    pause
    exit /b 1
  )
) else (
  echo       All packages are installed.
)

echo [3/3] Building the report ...
echo.
".venv\Scripts\python.exe" build_report.py
set RESULT=%errorlevel%

echo.
if %RESULT%==0 (
  echo Done. The output folder will open now.
  start "" "%~dp0output"
) else (
  echo Build failed with code %RESULT%. See output\build.log for details.
)

echo.
pause
exit /b %RESULT%
