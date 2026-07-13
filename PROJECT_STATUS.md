# Project Status

Last updated: 2026-07-12

## Current Phase

MVP Complete — Operational Automation Active

---

## Completed Milestones

### Phase 1 — Foundation (Complete)
- [x] PostgreSQL database schema (5 tables: teams, games, starting_pitchers, odds_history, team_records)
- [x] MLB Stats API integration — games, probable pitchers, team records (free, no key)
- [x] OddsAPI.io integration — Bet365 + DraftKings moneyline odds (free tier)
- [x] Ingestion script: `backend/scripts/save_live_data.py` — runs daily to populate all tables
- [x] All 30 MLB teams seeded

### Phase 2 — Backend API (Complete)
- [x] FastAPI server with CORS
- [x] `GET /health`
- [x] `GET /games/today`
- [x] `GET /games/today-with-odds` (games + latest odds + pitchers + records in one call)
- [x] `GET /odds/latest`
- [x] `GET /odds/today`
- [x] `GET /odds/movement` — opening vs latest moneyline, movement delta, optional filters
- [x] `GET /odds/movement/summary` — only non-zero movement rows, sorted by |movement| desc
- [x] `GET /research/today` — consolidated research endpoint (all data in one response)
- [x] `GET /teams`
- [x] Implied probability math (`backend/odds_math.py`)

### Phase 3 — Frontend (Complete)
- [x] Next.js app (TypeScript, App Router)
- [x] Today's games table with game time and status
- [x] Moneyline odds columns (Bet365 + DraftKings)
- [x] Implied probabilities per sportsbook
- [x] Probable pitchers columns
- [x] Team records columns
- [x] Line movement table (opening/latest/delta per sportsbook per side)
- [x] Dashboard refactored to use `GET /research/today` as the single data source

### Phase 4 — Research Layer Expansion (Complete)
- [x] Team Form v1 — last 10 games: record + run differential per team
- [x] Team Home/Away Splits v1 — road record for away team, home record for home team
- [x] Team Streaks v1 — current win/loss streak per team
- [x] All research data integrated into `GET /research/today`
- [x] Dashboard displays form, splits, and streak columns
- [x] Backfill support: `save_live_data.py --date YYYY-MM-DD`
- [x] Historical data verified — 9 dates, 105+ final games stored

### Phase 5 — Research Layer Hardening (Complete)
- [x] `GET /research/date/{date}` — historical research for any stored date
- [x] `GET /research/available-dates` — all distinct stored game dates, newest first
- [x] Shared helper `_get_research_for_date(conn, target_date)` — no logic duplication
- [x] Invalid date format returns 422 with clear message
- [x] Dashboard date selector replaced `<input type="date">` with API-powered `<select>`
- [x] Dashboard fetches available dates on load; dropdown shows only stored dates
- [x] Default loads today; selecting a date calls `/research/date/{date}`
- [x] Back to Today button clears selection and returns to `/research/today`
- [x] Regression tests: `backend/tests/test_research_endpoints.py` — 9 tests, all passing
- [x] Tests cover: status codes, response shape, research keys, date validation, routing

### Phase 6 — Operations Hardening (Complete)
- [x] `backend/scripts/run_ingestion.bat` — automation wrapper for Task Scheduler
- [x] Appends to `logs/ingestion.log` with start/end timestamps and exit code
- [x] Run timestamp added to `save_live_data.py` output
- [x] Register Task Scheduler tasks — "MLB Ingestion 11AM" and "MLB Ingestion 7PM"
- [x] Verified: test run on 2026-07-12 produced exit=0, 15 games saved, log written

### Phase 7 — Research UX (Complete)
- [x] `GET /game/{game_id}` — full research detail endpoint for a single game
- [x] Game detail page (`/game/[game_id]`) — dedicated research view per game
- [x] Data Quality Card — dashboard component showing data completeness warnings
- [x] Ingestion Status Card — dashboard component showing last run time + exit code
- [x] Research filters — checkboxes for Has Injuries, Has Significant Line Movement,
      Has Weather Context (additive AND logic)
- [x] Sort — Default or Largest Line Movement
- [x] Research flags — emoji badges (⚠ 📈 🌬) on each game row in the table
- [x] Flag summary bar — count of flagged games for the current filtered view
- [x] `frontend/lib/gameFilters.ts` — shared filter logic + LINE_MOVE_THRESHOLD
- [x] `frontend/lib/gameFlags.ts` — shared flag derivation logic
- [x] `frontend/lib/gameFlagSummary.ts` — shared flag summary aggregation
- [x] `frontend/components/ResearchFlags.tsx` — reusable badge renderer
- [x] Research Workspace — pin games via "+ Workspace" button, persisted in localStorage
- [x] Workspace Notes — per-game textarea (up to 1000 chars), persisted in localStorage
- [x] Comparison View — side-by-side table for 2 workspace games, auto-selects when
      exactly 2 games are in workspace; covers flags, records, pitchers, form,
      streaks, splits, weather, bullpen, injuries, moneylines, max line move
- [x] Frontend tests: 34 Vitest tests across gameFilters, gameFlags, gameFlagSummary

---

## Active Architecture

```
MLB Stats API ──┐
ESPN         ──┤
Open-Meteo   ──┼──► save_live_data.py ──► PostgreSQL
OddsAPI.io   ──┘         ▲
                          │
             run_ingestion.bat
             (Task Scheduler: 11 AM + 7 PM daily — ACTIVE)

PostgreSQL ──► FastAPI ──► /research/* ──► Next.js Dashboard
                                               │
                                        /game/[id] detail view
                                        Research Workspace
                                        Comparison View
```

---

## Current Data Sources

| Source | Data | Status |
|--------|------|--------|
| MLB Stats API | Games, pitchers, records, bullpen | Active (free, no key) |
| OddsAPI.io | Bet365 + DraftKings moneylines | Active (free tier) |
| ESPN | Injury reports | Active (free, no key) |
| Open-Meteo | Stadium weather | Active (free, no key) |
| SportsDataIO | Any MLB data | Paused (kept in `backend/fetchers/`) |

---

## Current Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Server health check |
| `GET /health/ingestion` | Last ingestion run time + exit code (feeds dashboard card) |
| `GET /health/data-quality` | Data completeness check (feeds dashboard card) |
| `GET /research/today` | All research data for today's games |
| `GET /research/date/{date}` | All research data for a historical date |
| `GET /research/available-dates` | All distinct stored game dates, newest first |
| `GET /game/{game_id}` | Full research detail for a single game |
| `GET /games/today` | Raw games only |
| `GET /odds/movement` | Line movement with filters |
| `GET /teams` | All 30 teams |

---

## Current Test Coverage

**Backend — 44 pytest tests (7 modules)**
- `test_research_endpoints.py` — 9 tests: /research/today, /research/date/{date}, /research/available-dates
- `test_weather.py` — 6 tests: weather fields, stadium coordinates (all 30 teams)
- `test_injuries.py` — 7 tests: player parsing, team mapping, edge cases
- `test_bullpen.py` — 7 tests: innings math, research endpoint integration
- `test_data_quality.py` — 6 tests: healthy/warning/failed states
- `test_game_detail.py` — 5 tests: 200/404, required keys, teams/records, weather null
- `test_health_ingestion.py` — 4 tests: log parsing for healthy/failed/missing/incomplete logs
- Run with: `backend/venv/Scripts/python.exe -m pytest backend/tests/ -v`
- Tests hit real local PostgreSQL — no mocks

**Frontend — 34 Vitest tests (3 modules)**
- `gameFilters.test.ts`, `gameFlags.test.ts`, `gameFlagSummary.test.ts`
- Run with: `cd frontend && npm test`

---

## Known Issues

- **Injury team mapping** — ESPN injury feed returns team names that don't all match
  the abbreviations in the `teams` table. Most injury rows are skipped at save time
  with "unknown team" in the log. Injury data is fetched correctly; the gap is
  in the save-side team-name-to-abbreviation mapping.
- **Open-Meteo occasional 503s** — transient; the ingestion script logs and skips
  affected stadiums, exits with code 0. Typically resolves on the next run.
- **Interactive only logon mode** — Task Scheduler tasks require an active user session.
  If the PC is asleep or logged out at 11 AM or 7 PM, that day's run is skipped.

## Task Scheduler Registration (Completed 2026-07-12)

Both tasks are registered and active on RICH-LAB:

```
schtasks /create /tn "MLB Ingestion 11AM" /tr "C:\Users\rich-\RICH-LABS\mlb-betting-edge\backend\scripts\run_ingestion.bat" /sc daily /st 11:00 /ru "rich-" /f
schtasks /create /tn "MLB Ingestion 7PM"  /tr "C:\Users\rich-\RICH-LABS\mlb-betting-edge\backend\scripts\run_ingestion.bat" /sc daily /st 19:00 /ru "rich-" /f
```

If tasks ever need to be re-registered (e.g., after a Windows reinstall), run
the commands above from any PowerShell prompt. The `/f` flag overwrites silently.
