# Project Status

Last updated: 2026-06-20

## Current Phase

Research Layer Expansion

---

## Completed Milestones

### Foundation (Phase 1)
- [x] PostgreSQL database schema (5 tables: teams, games, starting_pitchers, odds_history, team_records)
- [x] MLB Stats API integration — games, probable pitchers, team records (free, no key)
- [x] OddsAPI.io integration — Bet365 + DraftKings moneyline odds (free tier)
- [x] Ingestion script: `backend/scripts/save_live_data.py` — runs daily to populate all tables
- [x] All 30 MLB teams seeded

### Backend (Phase 2)
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

### Frontend (Phase 3)
- [x] Next.js app (TypeScript, App Router)
- [x] Today's games table with game time and status
- [x] Moneyline odds columns (Bet365 + DraftKings)
- [x] Implied probabilities per sportsbook
- [x] Probable pitchers columns
- [x] Team records columns
- [x] Line movement table (opening/latest/delta per sportsbook per side)
- [x] Dashboard refactored to use `GET /research/today` as the single data source

### Team Form v1 (Phase 3 continued)
- [x] `backend/services/team_form.py` — `get_team_last_10_form(conn, team_id, before_date)` service function
- [x] `GET /research/today` extended with `away_team_form` and `home_team_form` per game
- [x] Form data: last_10_games_count, last_10_wins, last_10_losses, last_10_record, last_10_run_diff
- [x] Safe fallback when fewer than 10 completed games exist (returns actual count)
- [x] Dashboard displays "Last 10: 7-3, Run Diff: +18" (or "Last N:" if fewer than 10 games)
- [x] Only uses completed final games with non-null scores; excludes today's games

---

## Active Architecture

```
MLB Stats API ──┐
                ├──► save_live_data.py ──► PostgreSQL
OddsAPI.io   ──┘

PostgreSQL ──► FastAPI ──► GET /research/today ──► Next.js Dashboard
```

---

## Current Data Sources

| Source | Data | Status |
|--------|------|--------|
| MLB Stats API | Games, pitchers, team records | Active (free, no key) |
| OddsAPI.io | Bet365 + DraftKings moneylines | Active (free tier) |
| SportsDataIO | Any MLB data | Paused (kept in `backend/fetchers/`) |

---

## Completed (Research Layer Expansion)

- [x] Line Movement Summary endpoint
- [x] Consolidated Research Layer endpoint
- [x] Dashboard Refactor v1
- [x] Research Layer verification completed
- [x] Dashboard uses `GET /research/today` as single data source
- [x] Team Form v1 added to `/research/today`
- [x] Dashboard displays Last 10 form with safe fallback
- [x] Backfill support added to `save_live_data.py` via `--date YYYY-MM-DD` argument
- [x] Completed-game ingestion verified — final scores and statuses saved correctly
- [x] Team Form v1 verified with real completed game data (wins, losses, run differential confirmed against source rows)
- [x] Team Home/Away Splits v1 added to `/research/today` — away team road record, home team home record
- [x] Dashboard displays road record for away team and home record for home team
- [x] Team Streaks v1 added to `/research/today` — current win/loss streak per team
- [x] Dashboard displays streak label (e.g. W3, L2) for away and home teams
- [x] `GET /research/date/{date}` added — historical research for any stored date (YYYY-MM-DD)
- [x] Shared logic extracted into `_get_research_for_date(conn, target_date)` — no duplication
- [x] Invalid date format returns 422 with clear message

---

## Current Focus

Research Layer Expansion — Next Feature Selection

## Next Build Target

Evaluate the next smallest Research Layer addition after Research Date Endpoint.
