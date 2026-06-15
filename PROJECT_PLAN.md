# MLB Betting Edge — Project Plan

## Goal

Build a personal research dashboard that gives an edge when betting on MLB games.
Focus areas: moneylines, player props, batter vs pitcher matchups, line movement, parlays.

---

## Build Phases

### Phase 1 — Foundation
- [x] Create project folder structure
- [x] Define MVP scope (see MVP_PLAN.md)
- [x] Step 1: Write database schema — 5 tables (teams, games, starting_pitchers, odds_history, team_records)
- [x] Step 2: Connect to free MLB Stats API and print live data
        - [x] Build fetchers/mlb_stats_api.py (games, pitchers, team records)
        - [x] Run test_mlb_stats_api.py
        - [x] See live MLB games + standings printed in terminal (no API key needed)
- [x] Step 3: Research odds providers (see docs/ODDS_PROVIDER_RESEARCH.md) — recommended: OddsAPI.io free tier
        - [x] Sign up for OddsAPI.io and confirm MLB moneyline access
        - [x] Run test_odds_api.py and see live MLB moneyline odds in terminal
        - [x] Build fetchers/odds_api_io.py (standardized moneyline odds)
- [x] Step 4: Connect to PostgreSQL and save data
        - [x] Build fetchers/odds_api_io.py and verify with test_odds_fetcher.py (no DB writes yet)
        - [x] Create PostgreSQL database connection
        - [x] Save teams and games to database
        - [x] Save moneyline odds to database (odds_history table)
        - [ ] Save starting pitchers and team records to database (not yet built)
- [x] Step 5: Build FastAPI read-only backend
        - [x] Install fastapi + uvicorn
        - [x] Create backend/main.py, backend/db.py, and routers/ (games, odds, teams)
        - [x] GET /health
        - [x] GET /games/today
        - [x] GET /odds/latest
        - [x] GET /teams
- [x] Step 6: Build Next.js page — today's games table (reads from FastAPI endpoints)
- [ ] Step 7: Add line movement view (odds history chart per game)

> **SportsDataIO is paused.** `backend/fetchers/sportsdataio.py` is fully
> written and ready, but not used yet. We may bring it back later if needed.
> See `backend/README.md` for details.

> **OddsAPI.io verified (2026-06-10).** Connection test passed —
> `backend/test_odds_api.py` printed live MLB moneyline odds for real games.
> Key facts learned during testing:
> - Sport slug is `baseball`, MLB is the league `usa-mlb` (not `mlb`)
> - Free tier locks the account to **2 sportsbooks**; this account is
>   locked to **Bet365** and **DraftKings**
> - Odds aren't posted for every game at once — some games show
>   "no odds posted yet" until closer to game time

> **Database verified (2026-06-12).** PostgreSQL 17.10 installed and
> running locally. `mlb_betting_edge` database created and
> `database/schema.sql` executed — all 5 tables exist (`odds_history`
> now includes a `sportsbook` column). `backend/scripts/test_db_connection.py`
> confirmed the connection, and `backend/scripts/save_live_data.py` saved
> real live data: 30 teams, 15 games, and 14 odds_history rows (Bet365 +
> DraftKings).

> **FastAPI backend verified (2026-06-12).** All 4 endpoints tested live
> against `mlb_betting_edge`: `GET /health` → `{"status": "ok"}`,
> `GET /games/today` → 10 games, `GET /odds/latest` → 28 rows,
> `GET /teams` → 30 teams. Read-only — no write endpoints, no auth, no
> frontend, no cloud deployment.
>
> **UTC date fix (2026-06-12).** `/games/today` was filtering on
> `date.today()` (the server's local date), which could disagree with
> `game_date` (computed from the MLB Stats API's UTC `gameDate`).
> `backend/routers/games.py` now filters on
> `datetime.now(timezone.utc).date()` for a consistent, explicit UTC
> "today." Also fixed `.env` loading in `backend/db.py` so
> `uvicorn --reload` picks up `DATABASE_URL` correctly. Both fixes tested
> live — `/games/today` still returns 10 games for 2026-06-12.

### Phase 2 — Backend API
- [x] Build FastAPI server
- [x] Endpoints for games, teams, odds (read-only)
- [ ] Endpoint for players
- [ ] Batter vs Pitcher stats endpoint
- [ ] Line movement tracking endpoint

### Phase 3 — Frontend Dashboard (Current — Dashboard MVP)

> **Dashboard MVP homepage done (2026-06-15).** Next.js 16 app created in
> `frontend/` (TypeScript, App Router, ESLint, no Tailwind). Homepage
> fetches `GET /games/today` and shows a table (Away Team, Home Team,
> Game Time, Status) with loading/error/empty states. Verified end to end
> in a real browser against the live PostgreSQL → FastAPI → Next.js
> stack. Two small backend additions were needed: CORS middleware (so the
> browser can call the API) and `game_time` added to the `/games/today`
> response (see `CURRENT_STATUS.md` for details).

> **Game date normalization fix complete (2026-06-15).** Root cause
> identified: `game_date` was derived from the MLB Stats API's UTC
> `gameDate` field instead of the schedule date (`dates[].date`), which
> split a single day's slate across two dates. Fixed in
> `backend/fetchers/mlb_stats_api.py` (`game_date` now uses the MLB
> schedule date) and `backend/scripts/save_live_data.py` (the UPSERT now
> refreshes `game_date`/`game_time` on conflict, and odds matching now
> handles the UTC rollover). Verified: `GET /games/today` returns all 10
> games for the tested slate, and the dashboard displays all 10 games.
> See `CURRENT_STATUS.md` for full details.

- [x] Set up Next.js project
- [x] Today's games page
- [ ] Team matchup page
- [ ] Player props page
- [ ] Batter vs Pitcher analysis page
- [ ] Line movement charts

### Phase 4 — Advanced Features
- [ ] Parlay builder
- [ ] Historical performance tracking
- [ ] Value bet alerts

### Phase 5 — Deployment
- [ ] Database → Supabase
- [ ] Backend → Railway
- [ ] Frontend → Vercel

---

## Key Decisions

- **MLB Stats API** (free, official) for games, pitchers, and team records — Version 1 data source
- **SportsDataIO** paused — may return later for odds data (paid after free trial)
- **PostgreSQL** for storage (handles relational data well)
- **FastAPI** for backend (fast, simple, Python-based)
- **Next.js** for frontend (React-based, easy to deploy on Vercel)

---

## Notes

- Start small: get data flowing before building the UI
- Test each piece before moving to the next
- Keep costs low during development (local DB, free tiers)
