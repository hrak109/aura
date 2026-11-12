@echo off
title Aura Security Matrix Portal
setlocal enabledelayedexpansion

:: 1. Force Administration Elevation
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [AURA] Launching administrative setup...
    powershell -Command "Start-Process '%~dpnx0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
cls
color 0A

echo.
echo  ======================================================
echo     ___   _   _  ____    ___
echo    / _ \ / \ / \/ __ \  /   \
echo   / /_\ / / \ / /__/ / / /_  \
echo  / /_  / /_/ / __  /  / /_/  /
echo /_/ /_/ \___/_/ /_/  /_/ /__/  BY HAISTELLAR
echo  ======================================================
echo.
echo  [SYSTEM] Checking environment setup...

:: 2. Verify Python Installation
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and make sure 'Add Python to PATH' is checked during setup.
    pause
    exit /b
)

:: 3. Configure Windows Defender Firewall Inbound Rules
echo  [FIREWALL] Configuring Windows Defender Firewall...
netsh advfirewall firewall show rule name="Aura Web Portal" >nul 2>&1
if %errorLevel% neq 0 (
    netsh advfirewall firewall add rule name="Aura Web Portal" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
    echo  [SUCCESS] Added inbound firewall rule for Aura Web Portal (Port 8000)
) else (
    echo  [FIREWALL] Inbound rule for Port 8000 already configured.
)

netsh advfirewall firewall show rule name="Aura WebRTC Stream" >nul 2>&1
if %errorLevel% neq 0 (
    netsh advfirewall firewall add rule name="Aura WebRTC Stream" dir=in action=allow protocol=TCP localport=1984 >nul 2>&1
    echo  [SUCCESS] Added inbound firewall rule for Aura WebRTC Streams (Port 1984)
) else (
    echo  [FIREWALL] Inbound rule for Port 1984 already configured.
)

netsh advfirewall firewall show rule name="Aura WebRTC Media (TCP)" >nul 2>&1
if %errorLevel% neq 0 (
    netsh advfirewall firewall add rule name="Aura WebRTC Media (TCP)" dir=in action=allow protocol=TCP localport=8555 >nul 2>&1
    echo  [SUCCESS] Added inbound firewall rule for Aura WebRTC Media (TCP Port 8555)
) else (
    echo  [FIREWALL] Inbound rule for TCP Port 8555 already configured.
)

netsh advfirewall firewall show rule name="Aura WebRTC Media (UDP)" >nul 2>&1
if %errorLevel% neq 0 (
    netsh advfirewall firewall add rule name="Aura WebRTC Media (UDP)" dir=in action=allow protocol=UDP localport=8555 >nul 2>&1
    echo  [SUCCESS] Added inbound firewall rule for Aura WebRTC Media (UDP Port 8555)
) else (
    echo  [FIREWALL] Inbound rule for UDP Port 8555 already configured.
)

:: 4. Install Dependencies
echo  [DEPENDENCY] Syncing Python dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt >nul 2>&1
if %errorLevel% neq 0 (
    echo  [WARN] Pip install returned errors. Installing core dependencies manually...
    python -m pip install fastapi uvicorn wyze-sdk jinja2 python-multipart requests urllib3 >nul 2>&1
)
echo  [SUCCESS] Core dependencies verified.

:: 5. Get Active LAN IP Address
for /f "tokens=*" %%a in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex (Get-NetRoute -DestinationPrefix 0.0.0.0/0).InterfaceIndex).IPAddress"') do (
    set LAN_IP=%%a
)

cls
echo.
echo  ==============================================================
echo     ___   _   _  ____    ___
echo    / _ \ / \ / \/ __ \  /   \   AURA HOME SECURITY MATRIX
echo   / /_\ / / \ / /__/ / / /_  \  VERSION 1.9.0 [STABLE]
echo  / /_  / /_/ / __  /  / /_/  /  BY HAISTELLAR CO.
echo /_/ /_/ \___/_/ /_/  /_/ /__/  
echo  ==============================================================
echo.
echo  [STATUS] AURA BARE-METAL SERVER ACTIVE ON YOUR LOCAL NETWORK.
echo.
echo  ==============================================================
echo   To connect and view streams on this computer:
echo   --^> http://localhost:8000
echo.
echo   To connect OTHER PCs, tablets, or phones on the same network:
echo   --^> http://!LAN_IP!:8000
echo  ==============================================================
echo.
echo  Press Ctrl+C inside this window to terminate the server.
echo.
echo  [CORE] Launching FastAPI Web Portal...
echo.

python main.py
pause
