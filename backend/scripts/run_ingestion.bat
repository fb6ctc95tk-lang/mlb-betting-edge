@echo off
cd /d "%~dp0..\.."

if not exist logs mkdir logs

for /f "delims=" %%i in ('powershell -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
echo. >> logs\ingestion.log
echo [%TS%] === INGESTION START === >> logs\ingestion.log

.\backend\venv\Scripts\python.exe .\backend\scripts\save_live_data.py >> logs\ingestion.log 2>&1
set EXIT_CODE=%ERRORLEVEL%

for /f "delims=" %%i in ('powershell -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
echo [%TS%] === INGESTION END exit=%EXIT_CODE% === >> logs\ingestion.log

exit /b %EXIT_CODE%
