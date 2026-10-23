@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo Run setup.bat first.
 pause
 exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -B "%~dp0main.py"
