@echo off
setlocal
where python >nul 2>nul || (echo G.O.D. setup incomplete: Python 3.11 or newer is required. & pause & exit /b 1)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" || (echo G.O.D. setup incomplete: Python 3.11 or newer is required. & pause & exit /b 1)
python -c "import tmco" >nul 2>nul || (echo G.O.D. setup incomplete: run 'python -m pip install .' in this folder first. & pause & exit /b 1)
python -m tmco.web
if errorlevel 1 (echo G.O.D. stopped because of an error. & pause)
