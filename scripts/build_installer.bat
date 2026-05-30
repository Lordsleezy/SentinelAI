@echo off
REM SentinelAI Complete Windows Installer Builder
REM Builds Python backend + Electron app into Windows installer
REM Requirements: Python 3.8+, Node.js 16+, npm, electron-builder

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo SentinelAI Windows Installer Builder
echo ============================================================
echo.

REM Step 1: Build Python backend
echo [1/3] Building Python backend...
echo.

call scripts\build_backend.bat
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Backend build failed!
    pause
    exit /b 1
)

echo.
echo [1/3] Backend build complete
echo.

REM Step 2: Create icon
echo [2/3] Creating application icon...
echo.

cd desktop-shell
node ..\create_icon.js
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Icon creation failed!
    cd ..
    pause
    exit /b 1
)
cd ..

echo.
echo [2/3] Icon creation complete
echo.

REM Step 3: Build Electron installer
echo [3/3] Building Electron installer...
echo.

cd desktop-shell

REM Install npm dependencies if needed
if not exist "node_modules" (
    echo Installing npm dependencies...
    call npm install
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: npm install failed!
        cd ..
        pause
        exit /b 1
    )
)

REM Build with electron-builder
call npm run dist
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Electron builder failed!
    cd ..
    pause
    exit /b 1
)

cd ..

echo.
echo ============================================================
echo SUCCESS!
echo ============================================================
echo.
echo Installer created:
dir /b installer_dist\*.exe
echo.
echo Installation size: Check above
echo Ready for distribution!
echo.
pause
