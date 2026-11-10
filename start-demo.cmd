@echo off
where pwsh.exe >nul 2>&1
if errorlevel 1 (
    echo PowerShell 7 is required. Install it and run this file again.
    pause
    exit /b 1
)
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_demo.ps1" %*
if errorlevel 1 (
    pause
    exit /b 1
)
