@echo off
rem Ryde demo launcher for Windows: double-click this file.
rem It only checks for Python 3.9 or newer, then hands over to tools\launch.py.
rem goto labels, not parenthesised if blocks: the "(3, 9)" in the version check
rem would close such a block early.
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
echo Python 3.9 or newer is needed to run the Ryde demo. Install it from https://www.python.org/downloads/ and then open this file again.
pause
exit /b 1

:run
%PY% tools\launch.py
if errorlevel 1 goto failed
exit /b 0

:failed
pause
exit /b 1
