@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Update the dashboard program (data is preserved)
echo ============================================================
echo.

echo [1/4] Checking the data folder ...
if not exist "data" mkdir "data"
if exist "output\8d-forms.json" if not exist "data\8d-forms.json" (
  copy /y "output\8d-forms.json" "data\8d-forms.json" >nul
  echo       Moved saved 8D forms to data\8d-forms.json
)
for %%F in ("اصلاح ایرادها.xlsx" "اصلاحات گروه‌بندی.xlsx") do (
  if exist "%%~F" if not exist "data\%%~F" (
    copy /y "%%~F" "data\%%~F" >nul
    echo       Moved %%~F to data\
  )
)
echo       Your data stays in the data folder.

echo [2/4] Getting the latest program files ...
if exist ".git" (
  where git >nul 2>nul
  if not errorlevel 1 (
    git pull --ff-only
    if errorlevel 1 echo       [WARN] git pull failed; continuing with current files.
  ) else (
    echo       git was not found; replace program files manually.
    echo       Keep the data folder so nothing is lost.
  )
) else (
  echo       This folder is not a git repository; replace program files manually.
  echo       Keep the data folder so nothing is lost.
)

echo [3/4] Checking packages ...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import pandas, openpyxl, rapidfuzz, jdatetime, docx" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Package installation failed.
    pause
    exit /b 1
  )
)
echo       Packages are ready.

echo [4/4] Rebuilding the report with your existing data ...
".venv\Scripts\python.exe" build_report.py
set RESULT=%errorlevel%

echo.
if %RESULT%==0 (
  echo Done. Your data was kept:
  echo   data\8d-forms.json            saved 8D forms
  echo   data\اصلاح ایرادها.xlsx       manual defect text fixes
  echo   data\اصلاحات گروه‌بندی.xlsx   manual grouping fixes
  echo   data\backups\                 automatic backups
  echo.
  echo To open the dashboard run serve.bat
) else (
  echo Build failed with code %RESULT%. See output\build.log
)
echo.
pause
exit /b %RESULT%
