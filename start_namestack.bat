@echo off
rem Double-click launcher for the SayMyName web app.
rem First run: creates a private Python environment (.venv) and installs
rem everything. Later runs start instantly.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

echo First run: setting things up (takes about a minute)...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo Python was not found on this computer.
    echo Install it from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" in the installer,
    echo then double-click this file again.
    echo.
    pause
    exit /b 1
)

%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -e ".[ai]"
if errorlevel 1 goto fail

:run
echo Starting SayMyName... your browser will open at http://127.0.0.1:8787
echo Keep this window open while you use it. Close it to stop SayMyName.
".venv\Scripts\python.exe" -m namestack.server %*
pause
exit /b 0

:fail
echo.
echo Setup failed. Delete the ".venv" folder and try again,
echo or open an issue on GitHub with the error above.
rd /s /q ".venv" 2>nul
pause
exit /b 1
