# Operations Guide — MLB Betting Edge

## Overview

Daily ingestion pulls today's games, odds, and team records from external APIs and saves them to the local PostgreSQL database. The ingestion script is `backend/scripts/save_live_data.py`, driven by the batch file `backend/scripts/run_ingestion.bat`.

---

## Scheduled Tasks

Two Task Scheduler jobs run ingestion daily:

| Task Name | Schedule | Purpose |
|---|---|---|
| `MLB Ingestion 11AM` | Daily at 11:00 AM | Captures morning lines and day's game slate |
| `MLB Ingestion 7PM` | Daily at 7:00 PM | Captures updated odds before evening games |

Both tasks call the same wrapper: `backend\scripts\run_ingestion.bat`.

### Required Configuration (S4U Logon Type)

Both tasks must be configured with **LogonType = S4U** (not Interactive). Interactive mode causes the task to fail with error `-2147020576` whenever no user session is active — for example, when the machine is sleeping or the screen is locked.

S4U allows the task to run under the `rich-` user account without an active desktop session. No stored password is required.

To verify both tasks have the correct configuration:

```powershell
$t = Get-ScheduledTask -TaskName "MLB Ingestion 11AM"
$t.Principal | Select-Object UserId, LogonType
$t.Settings | Select-Object StartWhenAvailable
```

Expected output:
```
UserId  LogonType
------  ---------
rich-   S4U

StartWhenAvailable
------------------
True
```

Run the same check for `MLB Ingestion 7PM`.

### To re-register from scratch (if tasks are deleted)

Run the following in an **elevated** PowerShell (Run as Administrator):

```powershell
$bat = "C:\Users\rich-\RICH-LABS\mlb-betting-edge\backend\scripts\run_ingestion.bat"
$p   = New-ScheduledTaskPrincipal -UserId "RICH-LAB\rich-" -LogonType S4U -RunLevel Limited

$action11  = New-ScheduledTaskAction -Execute $bat
$trigger11 = New-ScheduledTaskTrigger -Daily -At "11:00AM"
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "MLB Ingestion 11AM" -Action $action11 -Trigger $trigger11 -Settings $settings -Principal $p -Force

$action7   = New-ScheduledTaskAction -Execute $bat
$trigger7  = New-ScheduledTaskTrigger -Daily -At "7:00PM"
Register-ScheduledTask -TaskName "MLB Ingestion 7PM" -Action $action7 -Trigger $trigger7 -Settings $settings -Principal $p -Force
```

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
schtasks /run /tn "MLB Ingestion 11AM"
```

---

## Log Verification

Logs are written to `logs/ingestion.log` at the repo root. Every run appends three sections:

```
[2026-07-15 11:00:01] === INGESTION START ===
Run started: 2026-07-15 11:00:02
Fetching games for today from MLB Stats API...
  Found 14 games
...
Saved 14 games
Saved 30 team records
Saved 14 odds rows
[2026-07-15 11:00:18] === INGESTION END exit=0 ===
```

**What to check:**

| Item | Healthy value |
|------|--------------|
| `INGESTION START` line | Present with today's date and a time |
| `INGESTION END` line | Present, `exit=0` |
| Games found | > 0 on game days (0 is normal on off-days and All-Star break) |
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

### Task Last Result is -2147020576

This means the task is configured as **Interactive only** and no user session was active when it fired. Fix:

```powershell
# Must run as Administrator
$p = New-ScheduledTaskPrincipal -UserId "RICH-LAB\rich-" -LogonType S4U -RunLevel Limited
Set-ScheduledTask -TaskName "MLB Ingestion 11AM" -Principal $p
Set-ScheduledTask -TaskName "MLB Ingestion 7PM" -Principal $p
```

After applying, re-query to confirm `LogonType` shows `S4U` (displayed as `Interactive/Background` in schtasks output).

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
    Where-Object { $_.Message -like "*MLB Ingestion*" } |
    Select-Object -First 10 TimeCreated, Message
```

### Task is not running at all

```powershell
# Check task status
Get-ScheduledTask -TaskName "MLB Ingestion 11AM"
Get-ScheduledTask -TaskName "MLB Ingestion 7PM"

# Re-enable if disabled
Enable-ScheduledTask -TaskName "MLB Ingestion 11AM"
Enable-ScheduledTask -TaskName "MLB Ingestion 7PM"
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
