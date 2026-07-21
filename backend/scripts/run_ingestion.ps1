#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# Derive repo root from script location.
# $PSScriptRoot = .../mlb-betting-edge/backend/scripts
# Two Split-Path levels up = .../mlb-betting-edge
$repoRoot     = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$logFile      = Join-Path $repoRoot 'logs\ingestion.log'
$pythonExe    = Join-Path $repoRoot 'backend\venv\Scripts\python.exe'
$ingestScript = Join-Path $repoRoot 'backend\scripts\save_live_data.py'

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "[$ts] $Message"
}

try {
    # Preserve historical repo-root working directory for Python child processes.
    # save_live_data.py and its fetchers use load_dotenv() without an explicit
    # path, which may resolve relative to CWD depending on the dotenv version.
    Set-Location -LiteralPath $repoRoot

    # Ensure logs directory exists before first write
    $logsDir = Split-Path $logFile -Parent
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }

    Add-Content -Path $logFile -Value ''
    Write-Log '=== SCHEDULER START ==='

    # Phase 2: Network readiness — probe 8.8.8.8 up to 12 times before aborting
    $netMax   = 12
    $netReady = $false

    for ($attempt = 1; $attempt -le $netMax; $attempt++) {
        ping.exe -n 1 -w 1000 8.8.8.8 | Out-Null
        $probeExit = $LASTEXITCODE
        Write-Log "PROBE exit=$probeExit check=$attempt/$netMax"

        if ($probeExit -eq 0) {
            Write-Log "NETWORK READY (after $($attempt - 1) wait(s)) check=$attempt/$netMax"
            $netReady = $true
            break
        }

        if ($attempt -lt $netMax) {
            Write-Log "NETWORK WAIT: check $attempt/$netMax - not ready, retrying in 5s"
            Write-Log "SLEEP START check=$attempt/$netMax method=powershell duration=5s"
            Start-Sleep -Seconds 5
            Write-Log "SLEEP END check=$attempt/$netMax exit=0"
        }
    }

    if (-not $netReady) {
        Write-Log "NETWORK FAILED: no connectivity after $netMax/$netMax checks - all probes exhausted"
        Write-Log '=== INGESTION END exit=1 ==='
        exit 1
    }

    # Phase 3: Ingestion with retry — up to 3 attempts, 120s between failures
    $runMax   = 3
    $exitCode = 1

    for ($runAttempt = 1; $runAttempt -le $runMax; $runAttempt++) {
        Write-Log "=== INGESTION START (attempt $runAttempt/$runMax) ==="

        # Invoke Python via cmd.exe using Start-Process so the argument string is
        # appended to the process command line verbatim, bypassing PowerShell 5.1's
        # native-argument quoting path. This correctly handles paths with spaces,
        # uses OS-level stdout+stderr append, and propagates Python's exit code.
        $proc = Start-Process -FilePath $env:COMSPEC `
            -ArgumentList "/c `"$pythonExe`" `"$ingestScript`" >> `"$logFile`" 2>&1" `
            -Wait -NoNewWindow -PassThru
        $exitCode = $proc.ExitCode

        Write-Log "BACKEND EXIT=$exitCode"

        if ($exitCode -eq 0) {
            Write-Log '=== INGESTION END exit=0 ==='
            exit 0
        }

        Write-Log "INGESTION FAILED exit=$exitCode (attempt $runAttempt/$runMax)"

        if ($runAttempt -lt $runMax) {
            Write-Log 'RETRY: waiting 120s before next attempt'
            Write-Log "RETRY SLEEP START attempt=$runAttempt method=powershell duration=120s"
            Start-Sleep -Seconds 120
            Write-Log "RETRY SLEEP END attempt=$runAttempt exit=0"
        }
    }

    Write-Log "PERMANENT FAILURE: all $runMax attempts exhausted"
    Write-Log "=== INGESTION END exit=$exitCode ==="
    exit $exitCode

} catch {
    $errMsg = $_.Exception.Message
    try {
        Write-Log "UNEXPECTED ERROR: $errMsg"
        Write-Log '=== INGESTION END exit=1 ==='
    } catch {
        # Logging failed; nothing more can be done
    }
    exit 1
}
