@echo off
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-TOTK-iOS.ps1"
set "mngBuildExit=%ERRORLEVEL%"
echo.
echo Press any key to close this window...
pause >nul
exit /b %mngBuildExit%
