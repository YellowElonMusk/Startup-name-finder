@echo off
rem Double-click launcher for the SayMyName web app.
rem First run: installs Python if needed (no admin rights), creates a private
rem Python environment (.venv) and installs everything. Later runs start instantly.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto run

echo First run: setting things up (takes a minute or two)...

rem Find a working Python 3.9+. "python" can be the Microsoft Store stub,
rem so each candidate is actually run before it is trusted.
set "PY="
call :try_py py -3
if not defined PY call :try_py python
if not defined PY call :try_py "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto make_venv

echo.
echo Python was not found. Downloading it from python.org (about 25 MB)...
set "PYVER=3.12.10"
set "PYARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PYARCH=arm64"
set "PYSETUP=%TEMP%\python-%PYVER%-%PYARCH%.exe"
curl -L --fail -o "%PYSETUP%" "https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-%PYARCH%.exe"
if errorlevel 1 (
    powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-%PYARCH%.exe' -OutFile '%PYSETUP%'"
)
if not exist "%PYSETUP%" goto no_python
echo Installing Python for your user account (no admin needed)...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=0
del "%PYSETUP%" >nul 2>nul
call :try_py "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY goto no_python

:make_venv
%PY% -m venv .venv
if errorlevel 1 goto fail
rem Antivirus / company proxies that re-sign HTTPS break the old pip bundled with
rem Python; recent pip trusts the Windows certificate store, so upgrade it first.
rem (An unreachable index still exits 0 here, so truststore goes first; Python 3.9
rem lacks it and falls back to the plain upgrade.)
".venv\Scripts\python.exe" -m pip install --use-feature=truststore --upgrade pip >nul 2>nul
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -e ".[ai]"
if errorlevel 1 goto fail

:run
echo Starting SayMyName... your browser will open at http://127.0.0.1:8787
echo Keep this window open while you use it. Close it to stop SayMyName.
".venv\Scripts\python.exe" -m namestack.server %*
pause
exit /b 0

:try_py
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b 0

:no_python
echo.
echo Could not install Python automatically.
echo Install it from https://www.python.org/downloads/
echo IMPORTANT: tick "Add python.exe to PATH" in the installer,
echo then double-click this file again.
echo.
pause
exit /b 1

:fail
echo.
echo Setup failed. Delete the ".venv" folder and try again,
echo or open an issue on GitHub with the error above.
rd /s /q ".venv" 2>nul
pause
exit /b 1
