# Project Status

Last updated: 2026-06-20

## Current Phase

Operations Hardening

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

### Phase 6 — Operations Hardening (In Progress)
- [x] `backend/scripts/run_ingestion.bat` — automation wrapper for Task Scheduler
- [x] Appends to `logs/ingestion.log` with start/end timestamps and exit code
- [x] Run timestamp added to `save_live_data.py` output
- [x] Task Scheduler commands documented (not yet registered)
- [ ] Register Task Scheduler tasks (11 AM + optional 7 PM)

---

## Active Architecture

```
MLB Stats API ──┐
                ├──► save_live_data.py ──► PostgreSQL
OddsAPI.io   ──┘         ▲
                          │
                 run_ingestion.bat (manual or Task Scheduler)

PostgreSQL ──► FastAPI ──► /research/* ──► Next.js Dashboard
```

---

## Current Data Sources

| Source | Data | Status |
|--------|------|--------|
| MLB Stats API | Games, pitchers, team records | Active (free, no key) |
| OddsAPI.io | Bet365 + DraftKings moneylines | Active (free tier) |
| SportsDataIO | Any MLB data | Paused (kept in `backend/fetchers/`) |

---

## Current Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Server health check |
| `GET /research/today` | All research data for today's games |
| `GET /research/date/{date}` | All research data for a historical date |
| `GET /research/available-dates` | All distinct stored game dates, newest first |
| `GET /games/today` | Raw games only |
| `GET /odds/movement` | Line movement with filters |
| `GET /teams` | All 30 teams |

---

## Current Test Coverage

- `backend/tests/test_research_endpoints.py` — 9 regression tests
- Run with: `backend/venv/Scripts/python.exe -m pytest backend/tests/ -v`
- Coverage: `/research/today`, `/research/date/{date}`, `/research/available-dates`
- Tests hit real local PostgreSQL — no mocks

---

## Pending

- Register Task Scheduler tasks for automated daily ingestion
  - 11 AM: `schtasks /create /tn "MLB Ingestion 11AM" /tr "C:\Users\rich-\RICH-LABS\mlb-betting-edge\backend\scripts\run_ingestion.bat" /sc daily /st 11:00 /ru %USERNAME% /f`
  - 7 PM (optional): same command with `/tn "MLB Ingestion 7PM" /st 19:00`
