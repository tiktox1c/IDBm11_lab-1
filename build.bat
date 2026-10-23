@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%TEMP%"
set "PYINSTALLER_CONFIG_DIR=%TEMP%\pyinstaller"
if not exist "%TEMP%" mkdir "%TEMP%"
".venv\Scripts\python.exe" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
 echo PyInstaller is missing. Install it only after your approval:
 echo .venv\Scripts\python.exe -m pip install -r requirements-build.txt
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name "AI Test Generator" --workpath temp\build --distpath dist --specpath temp --paths . --hidden-import win32timezone --exclude-module win32com.test --exclude-module win32com.demos --collect-data docx main.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -B scripts\package_release.py
if errorlevel 1 exit /b 1
echo Release archives are in release.
if /i not "%~1"=="/nopause" pause
