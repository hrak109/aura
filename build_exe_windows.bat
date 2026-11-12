@echo off
title Aura EXE Builder
setlocal enabledelayedexpansion
color 0A

echo.
echo  ======================================================
echo   AURA HOME SECURITY MATRIX — Windows EXE Builder
echo   By Haistellar
echo  ======================================================
echo.

cd /d "%~dp0"

:: ── Step 1: Verify Python ─────────────────────────────────
echo [STEP 1] Checking Python installation...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.10+ and ensure "Add to PATH" is checked.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo         Found: %%v

:: ── Step 2: Upgrade pip silently ─────────────────────────
echo [STEP 2] Upgrading pip...
python -m pip install --upgrade pip --quiet

:: ── Step 3: Install app dependencies ─────────────────────
echo [STEP 3] Installing app dependencies from requirements.txt...
python -m pip install -r requirements.txt --quiet
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install requirements. Check your internet connection.
    pause
    exit /b 1
)

:: ── Step 4: Install PyInstaller ──────────────────────────
echo [STEP 4] Installing PyInstaller...
python -m pip install pyinstaller --quiet
if %errorLevel% neq 0 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python -m PyInstaller --version') do echo         PyInstaller version: %%v

:: ── Step 5: Clean previous build ─────────────────────────
echo [STEP 5] Cleaning previous build artifacts...
if exist "dist\Aura.exe" del /q "dist\Aura.exe"
if exist "build\aura" rmdir /s /q "build\aura"

:: ── Step 6: Run PyInstaller ───────────────────────────────
echo [STEP 6] Building Aura.exe — this may take 1-3 minutes...
echo (Check build_log.txt for full output)
echo.
python -m PyInstaller aura.spec --noconfirm --clean > build_log.txt 2>&1
if %errorLevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed! Check build_log.txt for errors.
    type build_log.txt
    pause
    exit /b 1
)

echo [DEBUG] PyInstaller exited with success (0). Checking if file exists...
if exist "dist\Aura.exe" (
    echo [DEBUG] YES! Aura.exe WAS CREATED by PyInstaller.
    echo [DEBUG] Size of file right now:
    dir "dist\Aura.exe" | findstr "Aura.exe"
    echo [DEBUG] If Aura.exe vanishes from the folder after this, Windows Defender instantly deleted it!
) else (
    echo [DEBUG] NO! Aura.exe was NEVER created, but PyInstaller reported success!
    echo [DEBUG] Last 20 lines of build_log.txt:
    powershell -command "Get-Content build_log.txt -Tail 20"
)
pause

:: ── Done ─────────────────────────────────────────────────
cls
echo.
echo  ======================================================
echo   [SUCCESS] Aura.exe built successfully!
echo.
echo   Location: %~dp0dist\Aura.exe
echo.
echo   To distribute:
echo   * Copy  dist\Aura.exe  to the target Windows machine
echo   * Place it in any folder and double-click to run
echo   * It will auto-create .env in the same folder
echo   * Browser opens automatically to http://localhost:8000
echo  ======================================================
echo.

explorer "%~dp0dist"
pause
