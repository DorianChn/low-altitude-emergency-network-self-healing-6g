@echo off
setlocal
cd /d "%~dp0\.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0\start_demo.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Demo startup failed. Review the message above and logs under %%TEMP%%\LowAlt6GPhase6.
  pause
)
exit /b %EXIT_CODE%
