@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install 64-bit Python 3.11 or newer from python.org.
  pause
  exit /b 1
)
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it and rerun START_GOD.bat.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0src"
py -3 -m tmco.web --data "%LOCALAPPDATA%\GOD"
if errorlevel 1 (
  echo G.O.D. could not start. Check the message above and your provider configuration.
  echo Safe diagnostic: py -3 -m tmco.web --data "%LOCALAPPDATA%\GOD" --doctor
  pause
)
