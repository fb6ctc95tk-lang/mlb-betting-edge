# Phase 13 / Phase 14 — Operational Decision Tree

**Project:** MLB Betting Edge  
**Created:** 2026-07-15  
**Status at creation:** Phase 14 Sprint 1 awaiting 7PM natural task validation; Phase 13 Sprint 4 Totals diagnostic gated.

---

## How to Use This Document

This is an operational reference only. It does not authorize any implementation work. Each path ends with a clear stop condition and a handoff to the Project Manager before any action is taken.

---

## Starting Point — 7PM Task Natural Validation

After the `MLB Ingestion 7PM` scheduled task fires at 7:00 PM (first natural run under S4U logon), follow the applicable path below.

**How to check:**

```powershell
schtasks /query /tn "MLB Ingestion 7PM" /v /fo LIST
```

Look for:
- `Last Run Time` — should reflect today at or after 7:00 PM
- `Last Result` — should be `0`
- `Logon Mode` — should show `Interactive/Background` (S4U)

Also confirm a new ingestion block appears in `logs/ingestion.log` with an `INGESTION END exit=0` line.

---

## Path A — 7PM Task Fails (Last Result ≠ 0)

### How to identify

- `Last Result` is any value other than `0`
- No new ingestion block appears in `logs/ingestion.log` after 7:00 PM
- Or the block appears but shows `exit=1` or a Python traceback

### Evidence to collect

1. Full `schtasks /query` output for both tasks
2. The relevant ingestion block from `logs/ingestion.log` (or note its absence)
3. Task Scheduler event log if available:

```powershell
Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" |
    Where-Object { $_.Message -like "*MLB Ingestion*" } |
    Select-Object -First 10 TimeCreated, Message
```

4. Machine power/sleep state at 7:00 PM (was the machine on? was the user logged in?)

### What to do

- **Do not run the Totals diagnostic.**
- **Do not modify Task Scheduler settings without Project Manager approval.**
- Report findings to Project Manager as a `SCHEDULED TASK ISSUE`.
- Return to Phase 14 — Operations Reliability for investigation.

### Likely investigation areas

| Area | What to check |
|---|---|
| Task Scheduler last result code | Look up the specific error code |
| Log block absent | Wrapper never launched — likely a session or power issue |
| Log block present with exit=1 | Wrapper launched; ingestion script failed — read the log |
| Power condition | `DisallowStartIfOnBatteries = True` — was machine on battery at 7PM? |
| Session condition | S4U should handle no-session; if still failing, re-verify LogonType |

---

## Path B — 7PM Succeeds, Odds Records = 0

### Trigger condition

- `Last Result = 0` ✓
- New ingestion block present with `INGESTION END exit=0` ✓
- Block contains `Found 0 odds records`

### Interpretation

Phase 14 Sprint 1 is operationally validated. Both scheduled tasks have now completed at least one successful unattended run under S4U.

Phase 13 Sprint 4 trigger condition remains unmet. This is expected if:
- The MLB All-Star break is still active (no regular season games scheduled)
- Sportsbooks have not yet posted lines for upcoming games
- OddsAPI.io has no odds data for the queried slate

### What to do

- **Do not run the Totals diagnostic.**
- Continue waiting for the first ingestion block where `Found N odds records` with N > 0.
- No code changes, no schema changes, no task changes required.
- Check `logs/ingestion.log` again after the next scheduled run (11AM or 7PM on the next game day).
- MLB regular season typically resumes the Thursday or Friday after the All-Star break.

### Status to report

> Phase 14 operationally validated. Phase 13 Sprint 4 trigger not yet met — odds records = 0. No action required. Monitor next game-day ingestion.

---

## Path C — 7PM Succeeds and Odds Records > 0

### Trigger condition

- `Last Result = 0` ✓
- New ingestion block present with `INGESTION END exit=0` ✓
- Block contains `Found N odds records` where **N > 0** ✓

### Interpretation

Phase 14 Sprint 1 is operationally validated. Phase 13 Sprint 4 trigger condition is met.

### What to do

1. Report to Project Manager:

> Phase 14 operationally validated. Phase 13 Sprint 4 trigger met — Found N odds records (N > 0). Controlled Totals diagnostic is eligible. Awaiting Project Manager approval to run.

2. **Wait for Project Manager approval before running the diagnostic.**

3. If approved, run exactly once:

```
backend/venv/Scripts/python.exe backend/scripts/diagnostics/check_oddsapi_totals.py
```

### Diagnostic constraints

- Do not increase `MAX_EVENTS_TO_CHECK` (must remain 3).
- Do not perform separate broad API scans.
- Do not retry repeatedly in the same session.
- Do not make exploratory OddsAPI calls outside the diagnostic script.
- Run from the project root directory.

### After the diagnostic runs, proceed to Path D, E, or F below.

---

## Path D — Totals Diagnostic: AVAILABLE

### Condition

The diagnostic returns populated bookmaker data for a Totals market. At least one inspected event shows a non-ML market name (e.g., a totals or over/under entry) with populated odds.

### Interpretation

Full-Game Totals data appears technically accessible via the current OddsAPI.io account and plan. This does not mean Totals support should be implemented immediately.

### What to do

- **Do not implement production Totals support.**
- Do not add new `MarketType` values to the database.
- Do not add Totals ingestion logic to `save_live_data.py`.
- Do not add Totals endpoints to the backend API.
- Do not add Totals display to the frontend.
- Record the diagnostic output with timestamp and evidence in the existing Phase 13 documentation.
- Report to Project Manager for a dedicated architecture planning sprint.

### Planning questions for Project Manager to answer before any implementation

1. Database — how should Totals odds rows be stored? New table or extension of the existing odds table?
2. Ingestion — what changes to `save_live_data.py` are needed, and in what order?
3. API response shape — what fields does OddsAPI.io return for Totals, and does the schema accommodate them?
4. `MarketType` expansion — what values are needed and how do they affect existing queries?
5. UI display — what should the Market Research Board show for Totals?
6. Market Opportunity mapping — how does the existing Research Insight Layer apply to Totals?

---

## Path E — Totals Diagnostic: NOT AVAILABLE

### Condition

The diagnostic finds populated bookmaker data (events with non-empty bookmakers), but all markets returned are `ML`. No Totals, over/under, or non-moneyline market names appear across any of the inspected events.

### Interpretation

Full-Game Totals data is not returned by the current OddsAPI.io account tier or plan. The current supported market (`FULL_GAME_MONEYLINE`) remains the only accessible market.

### What to do

- **Do not add Totals support.**
- **Do not add workaround data providers without Project Manager review.**
- Continue the `FULL_GAME_MONEYLINE`-only research platform roadmap.
- Record the diagnostic result with timestamp and evidence.
- Report to Project Manager.

### Possible next steps (Project Manager decision required)

- Continue building moneyline Research Insights (new divergence patterns, trend signals)
- Improve the Market Research Board (display, filtering, historical navigation)
- Workspace and UX improvements
- If a provider or plan change is desired, Project Manager opens a separate provider research sprint — do not independently research or contact providers

---

## Path F — Totals Diagnostic: STILL INCONCLUSIVE

### Condition

The diagnostic completes but cannot confirm availability or unavailability. This occurs when:

- All inspected events return empty bookmakers (no markets posted yet)
- Fewer than the minimum events have enough data to draw a conclusion
- HTTP 429 (rate limit) interrupts the run before evidence is collected
- API responses are inconsistent or structurally unexpected
- The events inspected happen to have no lines posted despite N > 0 in the ingestion run

### What to do

- **Do not implement Totals support.**
- **Do not retry the diagnostic in the same session.**
- Do not make additional exploratory OddsAPI calls to compensate.
- Record the exact reason for the inconclusive result and the exact number of API calls made.
- Report to Project Manager with the full diagnostic output.

### Project Manager decides

- Whether to schedule a recheck on a future game day with better odds coverage
- Whether to continue moneyline-only work in the interim
- The recheck follows the same gate: a fresh ingestion block must show `Found N odds records` where N > 0 before the diagnostic runs again

---

## Trigger Condition Reference

This table summarizes the gate that must be checked before any Totals diagnostic run:

| Evidence | Sufficient to trigger? |
|---|---|
| `INGESTION END exit=0` | No |
| `Found N games` where N > 0 | No |
| `Saved N games` where N > 0 | No |
| `Saved N odds rows` where N > 0 | No |
| `Found N odds records` where **N > 0** | **Yes** |

The trigger line is specifically `Found N odds records` in the OddsAPI.io fetch section of the ingestion log. All other counts are insufficient on their own.

---

## Supported Market Status

| Market | Status |
|---|---|
| `FULL_GAME_MONEYLINE` | Supported — ingested, stored, displayed |
| `FULL_GAME_TOTALS` | Unconfirmed — diagnostic pending |

No Totals support exists in the current codebase. No implementation work may begin until a diagnostic confirms availability and the Project Manager approves an architecture sprint.

---

## Document Maintenance

Update this document only when:
- A diagnostic produces a confirmed result (update Path D, E, or F with timestamp and outcome)
- A Project Manager decision resolves one of the open paths
- A new operational issue changes the flow before the 7PM validation is complete

Do not use this document to track feature development. Feature decisions belong in sprint planning documents.
