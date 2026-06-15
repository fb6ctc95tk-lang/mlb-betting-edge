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
        - [x] Save starting pitchers and team records to database
- [x] Step 5: Build FastAPI read-only backend
        - [x] Install fastapi + uvicorn
        - [x] Create backend/main.py, backend/db.py, and routers/ (games, odds, teams)
        - [x] GET /health
        - [x] GET /games/today
        - [x] GET /odds/latest
        - [x] GET /odds/today
        - [x] GET /games/today-with-odds
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

> **`GET /odds/today` added (2026-06-15).** Read-only endpoint returning
> the latest saved moneyline odds for today's games, one row per
> game/sportsbook (game_id, game_date, game_time, sportsbook, away_team,
> home_team, away_moneyline, home_moneyline, recorded_at). Tested live:
> 13 rows across 7 of today's 10 games (7 Bet365 + 6 DraftKings). No
> schema changes, no frontend changes yet. See `CURRENT_STATUS.md` for
> the example response.

> **`GET /games/today-with-odds` added (2026-06-15).** Combines
> `/games/today` and `/odds/today` into one read-only endpoint: today's
> games (game_id, game_date, game_time, away_team, home_team, status),
> each with an `odds` array of the latest moneyline per sportsbook
> (`"odds": []` if none yet). Tested live: 10 games returned, 13 odds
> rows across 7 games, 3 games with `"odds": []`, no duplicate
> sportsbook entries per game. Matches a direct PostgreSQL query. No
> schema changes, no frontend changes yet. See `CURRENT_STATUS.md` for
> the example response.

> **Implied probability added (2026-06-15).** New utility
> `backend/odds_math.py` (`american_odds_to_implied_probability()`)
> converts an American moneyline to a percentage, rounded to 2 decimals.
> `/games/today-with-odds` now returns `away_implied_probability` and
> `home_implied_probability` alongside each moneyline. Verified against
> known examples (`-110` → `52.38`, `-120` → `54.55`, `+100` → `50.00`,
> `+150` → `40.00`) and live against all 13 odds rows across 10 games —
> 0 mismatches. Read-only — no edge calculations, no picks, no schema
> changes, no frontend changes. See `CURRENT_STATUS.md` for the example
> response.

> **Dashboard now shows odds and implied probability (2026-06-15).**
> `frontend/app/page.tsx` now fetches `GET /games/today-with-odds` and adds
> Bet365 and DraftKings Moneyline + Implied Probability columns (shown as
> "Away / Home") to the existing games table. Missing sportsbook odds show
> `"-"` without hiding the game. Verified: `tsc --noEmit` passes, homepage
> returns HTTP 200, and all 10 games render with values matching the live
> API response (including the 4 games missing one or both sportsbooks). No
> backend, schema, or styling-framework changes. See `CURRENT_STATUS.md`
> for the full verification output.

> **`starting_pitchers` and `team_records` now populated (2026-06-15).**
> Both MLB Stats API fetchers already returned this data — no new API
> calls or fields needed. Added `save_starting_pitchers()` and
> `save_team_records()` to `save_live_data.py`, following the existing
> UPSERT pattern. Verified live: 10/10 games saved a starting-pitchers row
> (10/10 with at least one probable pitcher; 2 games still have one side
> as `TBD`/`null`), and all 30 teams have a 2026 team_records row with
> full win/loss + home/away splits. No schema changes, no frontend
> changes. As a side effect, `/games/today`'s
> `probable_home_pitcher`/`probable_away_pitcher` fields now return real
> data instead of always `null`. See `CURRENT_STATUS.md` for example rows.

> **`/games/today-with-odds` now includes pitchers and records
> (2026-06-15).** Extended the existing query in
> `backend/routers/games.py`: a `LEFT JOIN starting_pitchers` adds
> `away_pitcher`/`home_pitcher` (`null` if not announced), and a
> `DISTINCT ON (team_id) ... ORDER BY season DESC` query against
> `team_records` adds `away_record`/`home_record` formatted as
> `"wins-losses"`. Verified live: 10 games returned, 0 mismatches vs. a
> direct PostgreSQL query, both teams have a record for all 10 games, 2
> games have a `null` away_pitcher (not yet announced), and the `odds`
> array is unchanged (14 rows across 7 games). No schema, ingestion, or
> frontend changes. See `CURRENT_STATUS.md` for the example response.

> **Dashboard now shows pitchers and records (2026-06-15).**
> `frontend/app/page.tsx` adds four columns — Away Pitcher, Home Pitcher,
> Away Record, Home Record — between Status and the odds columns, using
> the existing `/games/today-with-odds` response. Same table layout, no
> Tailwind, no charts. A `null` pitcher renders as `"-"`. Verified live
> with a headless Chrome render: all 10 games rendered with 0 mismatches
> vs. the API response, including both `null` away-pitcher games showing
> `"-"`. No backend, schema, or ingestion changes. See `CURRENT_STATUS.md`
> for details.

- [x] Set up Next.js project
- [x] Today's games page
- [x] Display moneyline odds + implied probability on today's games page
- [x] Display probable pitchers and team records on today's games page
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
