@echo off
REM SentinelAI Python Backend Builder for Windows
REM Requires: Python 3.8+, PyInstaller installed in venv

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Building SentinelAI Python Backend
echo ============================================================
echo.

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Python virtual environment not found
    echo Please run: python -m venv venv
    echo Then: venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate virtual environment
call venv\Scripts\activate.bat
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Check if PyInstaller is installed
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

REM Build backend
echo.
echo Building backend executable...
echo.

python -m PyInstaller build_backend.spec --clean --noconfirm
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: PyInstaller build failed!
    echo Please check the errors above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo SUCCESS!
echo ============================================================
echo.
echo Backend executable created:
echo   build\sentinel_backend\sentinel_backend.exe
echo.
echo Size check:
cd build\sentinel_backend
dir sentinel_backend.exe
cd ..\..

echo.
pause
