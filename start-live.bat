@echo off
rem Ryde live launcher for Windows: double-click this file.
rem The live helper reads the privately delivered .env.live sidecar.
cd /d "%~dp0"
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto run
goto nopython

:nopython
echo Python 3.9 or newer is needed to run the Ryde live demo. Install it from https://www.python.org/downloads/ and then open this file again.
pause
exit /b 1

:run
%PY% tools\launch_live.py %*
if errorlevel 1 goto failed
exit /b 0

:failed
pause
exit /b 1
