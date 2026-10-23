@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "tools\InnoSetup\ISCC.exe" (
 echo Place the official Inno Setup 6 portable compiler in tools\InnoSetup.
 echo See README.md. This script does not install or download system components.
 pause
 exit /b 1
)
set "MODEL_STORE=%~1"
if not defined MODEL_STORE set "MODEL_STORE=%OLLAMA_MODELS%"
if not defined MODEL_STORE set /p "MODEL_STORE=Full path to existing Ollama model storage: "
if not defined MODEL_STORE exit /b 1
call build.bat /nopause
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -B scripts\stage_offline.py --models "%MODEL_STORE%"
if errorlevel 1 exit /b 1
"tools\InnoSetup\ISCC.exe" installer\offline.iss
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -B scripts\package_release.py
if errorlevel 1 exit /b 1
echo Offline installer is in release\AI-Test-Generator-Setup.exe
pause
