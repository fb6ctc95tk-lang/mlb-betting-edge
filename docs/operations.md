# Operations Guide — MLB Betting Edge

## Overview

Daily ingestion pulls today's games, odds, and team records from external APIs and saves them to the local PostgreSQL database. The ingestion script is `backend/scripts/save_live_data.py`, driven by the batch file `backend/scripts/run_ingestion.bat`.

---

## Scheduled Task Setup (Windows Task Scheduler)

Run this once in PowerShell as Administrator to register the task. Replace the path if your repo is in a different location.

```powershell
$repoRoot = "C:\Users\rich-\RICH-LABS\mlb-betting-edge"
$bat      = "$repoRoot\backend\scripts\run_ingestion.bat"

$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -Daily -At "8:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName   "MLB-BettingEdge-Ingestion" `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Description "Daily MLB game, odds, and team record ingestion"
```

`-StartWhenAvailable` means if the machine was off at 8 AM, the task runs as soon as it boots up that day.

### Verify the task was registered

```powershell
Get-ScheduledTask -TaskName "MLB-BettingEdge-Ingestion" | Select-Object TaskName, State
```

Expected output:

```
TaskName                     State
--------                     -----
MLB-BettingEdge-Ingestion    Ready
```

---

## Recommended Schedule

| Run time | Reason |
|----------|--------|
| **8:00 AM daily** | Captures overnight odds lines and the day's scheduled games before afternoon action begins |

If you want a second daily pull to capture late-breaking lineup and odds changes, add a second trigger at **12:00 PM**.

---

## Manual Execution

To run ingestion immediately (e.g., after a missed day or to test):

```powershell
# From the repo root
.\backend\scripts\run_ingestion.bat
```

Or to pull data for a specific past date:

```powershell
.\backend\venv\Scripts\python.exe .\backend\scripts\save_live_data.py --date 2026-06-19
```

To trigger the scheduled task manually without waiting for its schedule:

```powershell
Start-ScheduledTask -TaskName "MLB-BettingEdge-Ingestion"
```

---

## Log Verification

Logs are written to `logs/ingestion.log` at the repo root. Every run appends three sections:

```
[2026-06-20 04:00:55] === INGESTION START ===
Run started: 2026-06-20 04:00:56
Fetching games for today from MLB Stats API...
  Found 14 games
...
Saved 14 games
Saved 14 starting pitcher rows (14 with a probable pitcher)
Saved 30 team records
Saved 14 odds rows
[2026-06-20 04:00:58] === INGESTION END exit=0 ===
```

**What to check:**

| Item | Healthy value |
|------|--------------|
| `INGESTION START` line | Present with today's date and a time |
| `INGESTION END` line | Present, `exit=0` |
| Games found | > 0 on game days (0 is normal on off-days) |
| Team records | 30 |
| Odds rows | Matches or is close to games count |

**Quick check command** — shows the last 20 lines:

```powershell
Get-Content logs\ingestion.log -Tail 20
```

**Check last run's exit code:**

```powershell
Select-String "INGESTION END" logs\ingestion.log | Select-Object -Last 1
```

---

## Troubleshooting

### `exit=1` — ingestion failed

1. Open the log and read the lines between START and END for that run.
2. Common causes:

   | Error in log | Fix |
   |---|---|
   | `DATABASE_URL is not set` | Check that `backend/.env` exists and contains `DATABASE_URL=...` |
   | `FAILED to connect to the database` | Confirm PostgreSQL is running: `Get-Service postgresql*` |
   | `RuntimeError` on odds fetch | OddsAPI.io key may be expired or quota exhausted — check your dashboard |
   | `ModuleNotFoundError` | Run `backend\venv\Scripts\pip install -r backend\requirements.txt` |

### Task ran but log shows no new entry

The task may have failed to launch the batch file. Check the Task Scheduler history:

```powershell
Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" |
    Where-Object { $_.Message -like "*MLB-BettingEdge*" } |
    Select-Object -First 10 TimeCreated, Message
```

### Task is not running at all

```powershell
# Check task status
Get-ScheduledTask -TaskName "MLB-BettingEdge-Ingestion"

# Re-enable if disabled
Enable-ScheduledTask -TaskName "MLB-BettingEdge-Ingestion"
```

### Remove and re-register the task

```powershell
Unregister-ScheduledTask -TaskName "MLB-BettingEdge-Ingestion" -Confirm:$false
# Then re-run the registration block above
```

---

## Log Rotation (optional)

The log file grows indefinitely. To trim it to the last 500 lines once it gets large:

```powershell
$log = "logs\ingestion.log"
$lines = Get-Content $log
if ($lines.Count -gt 500) {
    $lines | Select-Object -Last 500 | Set-Content $log -Encoding utf8
}
```

You can add this as a second scheduled task running monthly, or run it manually when needed.
