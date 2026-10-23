@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
set "PIP_CACHE_DIR=%TEMP%\pip-cache"
if not exist "%TEMP%" mkdir "%TEMP%"
set "PY_CMD=py -3"
py -3 -c "import sys;sys.exit(not sys.version_info[:2] >= (3,11))" >nul 2>&1
if errorlevel 1 (
 set "PY_CMD=python"
 python -c "import sys;sys.exit(not sys.version_info[:2] >= (3,11))" >nul 2>&1
 if errorlevel 1 goto missing
)
echo This installs Python packages into .venv in this folder.
echo Internet is required. Python and Ollama are not installed by this script.
choice /c YN /n /m "Continue? [Y/N]: "
if errorlevel 2 exit /b 0
if not exist ".venv\Scripts\python.exe" %PY_CMD% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Double-click run.bat.
pause
exit /b 0
:missing
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Enable Python launcher and Tcl/Tk during installation, then run setup.bat again.
pause
exit /b 1
:failed
echo Setup failed. Check internet, free space and folder permissions.
pause
exit /b 1
