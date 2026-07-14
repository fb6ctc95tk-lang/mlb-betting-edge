# OddsAPI.io Totals Diagnostic Runbook

**Diagnostic script:** `backend/scripts/diagnostics/check_oddsapi_totals.py`
**Purpose:** Determine whether the existing OddsAPI.io free-tier account returns
Full-Game Totals (over/under) market data for MLB events.
**Status as of 2026-07-14:** STILL INCONCLUSIVE — All-Star break prevented testing.

---

## When to Run

Run this diagnostic only after confirming **both** of the following:

1. The 11 AM scheduled ingestion has completed for the day (Task Scheduler ran, exit=0).
2. The ingestion log shows `Found N odds records` where **N > 0**.

**Critical distinction:** "Games saved" in the log does not mean bookmaker odds are populated.
The July 12 ingestion run shows this clearly:

```
Saved 15 games          ← games exist
Found 0 odds records    ← bookmakers posted NO lines
```

A run with `exit=0` but `Found 0 odds records` means the API returned no bookmaker
data for that day. Running the diagnostic against empty bookmaker events will produce
INCONCLUSIVE regardless of the totals question.

---

## Step-by-Step Procedure

### Step A — Wait for the 11 AM ingestion

The Task Scheduler task "MLB Ingestion 11AM" runs at 11:00 AM daily.
Do not run the diagnostic before it fires.

To verify the task ran, either:
- Wait until approximately 11:05 AM, or
- Check Task Scheduler:
  ```
  schtasks /query /tn "MLB Ingestion 11AM" /fo LIST /v
  ```
  Look for `Last Run Time` showing today's date.

### Step B — Check the ingestion log

Open `logs/ingestion.log` and find the most recent entry. Confirm it shows today's
date and that it contains:

```
Found N odds records
```

where N is **greater than zero**.

Example of a run that confirms odds are available (July 5):
```
[2026-07-05 11:00:02] === INGESTION START ===
...
Fetching moneyline odds from OddsAPI.io...
  Found 12 odds records
...
[2026-07-05 11:00:20] === INGESTION END exit=0 ===
```
This is a valid pre-condition. N=12 > 0.

Example of a run that does NOT confirm odds (July 12):
```
[2026-07-12 21:59:47] === INGESTION START ===
...
Fetching moneyline odds from OddsAPI.io...
  Found 0 odds records
...
[2026-07-12 22:00:06] === INGESTION END exit=0 ===
```
This is NOT a valid pre-condition. Do not run the diagnostic against this state.

### Step C — Only if Step B confirms N > 0, run the diagnostic

From the project root (`mlb-betting-edge/`):

```
backend/venv/Scripts/python.exe backend/scripts/diagnostics/check_oddsapi_totals.py
```

The script makes at most **6 API requests** (free tier allows 100/hour):
- 1 request: events list
- Up to 3 requests: raw odds per event (first 3 pending events by date)
- Up to 2 requests: market parameter probes (`markets=totals`, `markets=ML,totals`)
  — only run when at least one event has populated bookmaker data

### Step D — Read the output and record the verdict

The script prints one of three verdicts:

| Verdict | Meaning |
|---------|---------|
| `Non-ML markets observed : YES` | Full-Game Totals data appeared |
| `Non-ML markets observed : NO` | Events had ML data but no totals |
| `Non-ML markets observed : INCONCLUSIVE` | Events still had empty bookmakers |

---

## Verdict Rules

### AVAILABLE

Use only when all of the following are true:
- At least one bookmaker response is populated (not empty)
- That response includes a market with name other than "ML"
- The market contains recognizable Over/Under selections and a numeric total line
- The result appears for more than one event if enough events have active lines

### NOT AVAILABLE

Use only when all of the following are true:
- Multiple events have populated bookmaker responses (confirmed ML data exists)
- Those same responses contain only "ML" — no totals market appears
- OR the API returns an explicit entitlement/plan error on totals requests

Do not declare NOT AVAILABLE because a single game lacks totals. Some games may
not have totals posted even when the market is generally available.

### STILL INCONCLUSIVE

Use when:
- All inspected events returned empty bookmakers
- The ingestion log showed N > 0 but the diagnostic events had no data
- Responses were inconsistent across events
- The request budget was exhausted before a conclusion was reached

---

## Known Limitation

The diagnostic script inspects the first 3 pending events sorted by game time.
It **cannot pre-verify** which of those events have bookmaker data posted without
actually making the odds request. This is by design — adding a broader pre-scan
would consume API budget without improving the conclusion.

Consequence: if the three earliest pending events happen to be games that
bookmakers have not yet priced (e.g., early-week series openers), the diagnostic
may return INCONCLUSIVE even on a day when later games have active lines.

If INCONCLUSIVE is returned after the ingestion log confirmed N > 0 odds:
- The odds in the log belong to events that the production fetcher processed
- The production fetcher processes the first `max_games=10` events by date
- The diagnostic inspects the first 3 of those same events
- If the first 3 events have empty bookmakers but the ingestion found odds on
  events 4–10, the diagnostic will miss them

In this scenario, do not add a broader scan. Document the result as INCONCLUSIVE
and try again the following day, or note that the overlap between the first 3
diagnostic events and the 10 production events was partial.

---

## What to Record After the Run

Update `docs/MARKET_RESEARCH_ARCHITECTURE.md` Section 6.2 with:
- Date and time of test
- Ingestion log pre-check result (N odds records)
- Number of events inspected
- Number of events with populated bookmakers
- Market names observed per bookmaker
- Final verdict (AVAILABLE / NOT AVAILABLE / STILL INCONCLUSIVE)
- Any totals example response fields if verdict is AVAILABLE

---

## What Not to Do

- Do not run a 50-event scan. It burned the Sprint 2 rate budget.
- Do not run the diagnostic without first checking the ingestion log.
- Do not conclude NOT AVAILABLE from empty bookmakers — that is INCONCLUSIVE.
- Do not implement totals storage, schema changes, or production fetcher updates
  based on this diagnostic alone. A AVAILABLE verdict requires Project Manager
  review before any implementation sprint begins.
