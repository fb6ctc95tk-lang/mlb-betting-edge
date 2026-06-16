# Project Status

Last updated: 2026-06-16

## Current Phase

Phase 1 MVP — complete. Phase 3 dashboard features complete through Research Layer refactor.

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

## What's Next (not started)

- Team matchup detail page
- Player props page
- Batter vs Pitcher analysis
- Line movement charts
- Cloud deployment (Supabase + Railway + Vercel)

See `PROJECT_PLAN.md` for the full roadmap.
