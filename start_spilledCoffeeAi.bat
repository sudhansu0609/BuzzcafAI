@echo off
setlocal enabledelayedexpansion

REM ===================================================
REM spilledCoffeeAi Application Startup Launcher
REM ===================================================

REM Define ports matching frontend vite.config.ts and backend app/main.py
set FRONTEND_PORT=3005
set BACKEND_PORT=8095

echo ===================================================
echo Starting spilledCoffeeAi Application...
echo ===================================================

REM Stop processes using the configured ports if they exist
echo Checking and clearing active ports %FRONTEND_PORT% and %BACKEND_PORT%...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT%,%BACKEND_PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM Get current working directory of the batch file
set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"
set "BACKEND_DIR=%APP_DIR%backend"
set "PYTHON_EXE=%BACKEND_DIR%\voice_env\Scripts\python.exe"

REM Check for virtual environment python or fallback to system python
if not exist "%PYTHON_EXE%" (
    echo [WARN] Virtual environment python not found at "%PYTHON_EXE%". Falling back to system python.
    set "PYTHON_EXE=python"
)

echo Starting spilledCoffeeAi Frontend UI on port %FRONTEND_PORT%...
start "spilledCoffeeAi Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo Starting spilledCoffeeAi FastAPI Backend on port %BACKEND_PORT%...
start "spilledCoffeeAi Backend" cmd /k "cd /d "%BACKEND_DIR%" && set PYTHONIOENCODING=utf-8 && "%PYTHON_EXE%" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload"

echo.
echo ===================================================
echo spilledCoffeeAi Application started successfully!
echo.
echo Frontend Web Studio : http://localhost:%FRONTEND_PORT%
echo Backend FastAPI Engine: http://localhost:%BACKEND_PORT%
echo ===================================================
echo.
pause
