@echo off
REM dockur OEM: runs at end of unattended Windows install (C:\OEM).
setlocal
cd /d %~dp0
echo ansible-flow lab OEM (win-server) starting > "%~dp0oem-start.log"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-winrm.ps1" >> "%~dp0oem-run.log" 2>&1
echo exit=%ERRORLEVEL% >> "%~dp0oem-start.log"
endlocal
