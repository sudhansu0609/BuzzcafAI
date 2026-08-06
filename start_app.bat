@echo off
setlocal enabledelayedexpansion

REM Define ports matching vite.config.ts and app/main.py
set FRONTEND_PORT=3005
set BACKEND_PORT=8095

echo ===================================================
echo Starting MidnightBuzz Application...
echo ===================================================

REM Stop processes using the configured ports if they exist
echo Checking and clearing ports %FRONTEND_PORT% and %BACKEND_PORT%...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT%,%BACKEND_PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM Get current directory of the batch file
set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"
set "BACKEND_DIR=%APP_DIR%backend"
set "PYTHON_EXE=%BACKEND_DIR%\voice_env\Scripts\python.exe"

REM Fallback to system python if virtual environment python doesn't exist
if not exist "%PYTHON_EXE%" (
    echo [WARN] Virtual environment python not found at "%PYTHON_EXE%". Using system python.
    set "PYTHON_EXE=python"
)

echo Starting Frontend on port %FRONTEND_PORT%...
start "MidnightBuzz Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo Starting Backend on port %BACKEND_PORT%...
start "MidnightBuzz Backend" cmd /k "cd /d "%BACKEND_DIR%" && set PYTHONIOENCODING=utf-8 && "%PYTHON_EXE%" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload"

echo.
echo ===================================================
echo MidnightBuzz Application started successfully!
echo Frontend: http://localhost:%FRONTEND_PORT%
echo Backend:  http://localhost:%BACKEND_PORT%
echo ===================================================
echo.
pause