@echo off
setlocal
REM ===================================================
REM Buzzcaf Studio - developer launcher (one console, live-reloading UI)
REM
REM Day-to-day use: double-click "Buzzcaf Studio.vbs" instead. It opens only
REM the app window, no console. This script is for working on the code: it
REM runs the same desktop shell with --dev, which serves our Vite dev server
REM (port 5173, or the next free one when another project's Vite is there;
REM hot reload) inside the window and prints the log here.
REM
REM Interpreter: BUZZCAF_PYTHON -> .venv\Scripts\python.exe -> python on PATH.
REM ===================================================
set "APP_DIR=%~dp0"
set "PYTHON_EXE="
if defined BUZZCAF_PYTHON if exist "%BUZZCAF_PYTHON%" set "PYTHON_EXE=%BUZZCAF_PYTHON%"
if not defined PYTHON_EXE if exist "%APP_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%APP_DIR%.venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo ===================================================
echo  Buzzcaf Studio (developer mode)
echo  Interpreter: %PYTHON_EXE%
echo ===================================================
set PYTHONIOENCODING=utf-8
"%PYTHON_EXE%" -X utf8 "%APP_DIR%backend\desktop_app.py" --dev
echo.
echo Buzzcaf Studio closed. Log: backend\logs\studio.log
pause
