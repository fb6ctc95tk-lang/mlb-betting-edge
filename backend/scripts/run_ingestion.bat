@echo off
cd /d "%~dp0..\.."

if not exist logs mkdir logs

:: PHASE 1: SCHEDULER START
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
echo. >> logs\ingestion.log
echo [%TS%] === SCHEDULER START === >> logs\ingestion.log

:: PHASE 2: WAIT FOR NETWORK READINESS
:: After a sleep wake, the network stack may not be ready immediately.
:: Ping a reliable IP (no DNS needed) up to 12 times (~60s) before aborting.
set NET_ATTEMPT=0
set NET_MAX=12

:WAIT_NETWORK
ping -n 1 -w 1000 8.8.8.8 >nul 2>&1
if not errorlevel 1 goto NETWORK_READY

set /a NET_ATTEMPT+=1
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
if %NET_ATTEMPT% geq %NET_MAX% (
    echo [%TS%] NETWORK FAILED: no connectivity after %NET_MAX% checks - aborting >> logs\ingestion.log
    echo [%TS%] === INGESTION END exit=1 === >> logs\ingestion.log
    exit /b 1
)
echo [%TS%] NETWORK WAIT: check %NET_ATTEMPT%/%NET_MAX% - not ready, retrying in 5s >> logs\ingestion.log
ping 127.0.0.1 -n 6 -w 1000 >nul 2>&1
goto WAIT_NETWORK

:NETWORK_READY
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
echo [%TS%] NETWORK READY (after %NET_ATTEMPT% wait(s)) >> logs\ingestion.log

:: PHASE 3: RUN INGESTION WITH RETRY
:: Retries up to RUN_MAX times with 120s between attempts.
:: Handles transient network errors that survive the initial readiness check.
set RUN_ATTEMPT=0
set RUN_MAX=3

:RUN_INGESTION
set /a RUN_ATTEMPT+=1
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i
echo [%TS%] === INGESTION START (attempt %RUN_ATTEMPT%/%RUN_MAX%) === >> logs\ingestion.log

.\backend\venv\Scripts\python.exe .\backend\scripts\save_live_data.py >> logs\ingestion.log 2>&1
set EXIT_CODE=%ERRORLEVEL%

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set TS=%%i

if %EXIT_CODE% equ 0 (
    echo [%TS%] === INGESTION END exit=0 === >> logs\ingestion.log
    exit /b 0
)

echo [%TS%] INGESTION FAILED exit=%EXIT_CODE% (attempt %RUN_ATTEMPT%/%RUN_MAX%) >> logs\ingestion.log

if %RUN_ATTEMPT% lss %RUN_MAX% (
    echo [%TS%] RETRY: waiting 120s before next attempt >> logs\ingestion.log
    ping 127.0.0.1 -n 121 -w 1000 >nul 2>&1
    goto RUN_INGESTION
)

echo [%TS%] PERMANENT FAILURE: all %RUN_MAX% attempts exhausted >> logs\ingestion.log
echo [%TS%] === INGESTION END exit=%EXIT_CODE% === >> logs\ingestion.log
exit /b %EXIT_CODE%
