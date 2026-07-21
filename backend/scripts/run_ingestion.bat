@echo off
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0run_ingestion.ps1"
set "WRAPPER_EXIT=%ERRORLEVEL%"
exit /b %WRAPPER_EXIT%
