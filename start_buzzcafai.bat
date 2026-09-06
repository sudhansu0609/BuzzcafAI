@echo off
setlocal enabledelayedexpansion

REM ===================================================
REM Buzzcaf AI Studio - Startup Launcher
REM
REM Starts the frontend and backend from THIS checkout.
REM The previous launcher pointed at a sibling folder, so edits made here
REM appeared to have no effect. Always use %APP_DIR% paths below.
REM
REM Ports match frontend/vite.config.ts (5173) and its proxy target (8000).
REM Change them in vite.config.ts and here together, or override below.
REM ===================================================

if "%FRONTEND_PORT%"=="" set FRONTEND_PORT=5173
if "%BACKEND_PORT%"==""  set BACKEND_PORT=8000

echo ===================================================
echo Starting Buzzcaf AI Studio...
echo ===================================================

REM Free the ports if a previous run is still holding them
echo Clearing active ports %FRONTEND_PORT% and %BACKEND_PORT%...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %FRONTEND_PORT%,%BACKEND_PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

set "APP_DIR=%~dp0"
set "FRONTEND_DIR=%APP_DIR%frontend"
set "BACKEND_DIR=%APP_DIR%backend"
set "PYTHON_EXE=%BACKEND_DIR%\voice_env\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [WARN] Virtual environment python not found at "%PYTHON_EXE%". Falling back to system python.
    set "PYTHON_EXE=python"
)

echo Starting Frontend UI on port %FRONTEND_PORT%...
start "Buzzcaf Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev -- --port %FRONTEND_PORT%"

REM Bound to 127.0.0.1 on purpose: the API serves settings and project data with
REM no authentication, so it must not be reachable from the rest of the LAN.
echo Starting FastAPI Backend on port %BACKEND_PORT%...
start "Buzzcaf Backend" cmd /k "cd /d "%BACKEND_DIR%" && set PYTHONIOENCODING=utf-8 && "%PYTHON_EXE%" -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

echo.
echo ===================================================
echo Buzzcaf AI Studio started.
echo.
echo Frontend Web Studio    : http://localhost:%FRONTEND_PORT%
echo Backend FastAPI Engine : http://127.0.0.1:%BACKEND_PORT%
echo ===================================================
echo.
pause
