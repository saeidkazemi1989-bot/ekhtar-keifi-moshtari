@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Required runtime is missing. Extract the entire ZIP file before running.
  pause
  exit /b 1
)
if not exist "output\index.html" (
  echo Building the initial report. Please wait...
  "runtime\python.exe" build_report.py
  if errorlevel 1 (
    echo Failed to build the report. See output\build.log.
    pause
    exit /b 1
  )
)
echo Starting dashboard. Keep this window open while using it.
"runtime\python.exe" serve.py --port 8000
if errorlevel 1 (
  echo The dashboard could not start. If another copy is running, close it and try again.
  pause
  exit /b 1
)
