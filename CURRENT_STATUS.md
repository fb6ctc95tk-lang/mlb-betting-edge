# Current Status — MLB Betting Edge

**Last updated:** 2026-06-15
**Current Phase:** Phase 3 — Dashboard MVP (homepage built and verified)

This file is a "save point" for the project. If you take a break and come
back later (or open a new chat with Claude Code), read this file first —
it explains exactly what's working, what's been tested, and what to do next.

---

## 1. What Currently Works

- **Project structure** — folders for backend, frontend, database, and docs
  are all set up (see `README.md` for the full layout).
- **PostgreSQL database is live** — PostgreSQL 17.10 is installed and
  running locally. The `mlb_betting_edge` database exists, and
  `database/schema.sql` has been executed successfully — all 5 tables
  exist: `teams`, `games`, `starting_pitchers`, `odds_history` (now
  includes a `sportsbook` column), and `team_records`.
- **Free MLB game data** — `backend/fetchers/mlb_stats_api.py` can fetch
  today's games, scores, starting pitchers, and team win/loss records from
  the official free MLB Stats API. No API key needed.
- **MLB odds data** — `backend/fetchers/odds_api_io.py` can fetch live
  moneyline odds (the "who's favored to win" numbers) for MLB games from
  OddsAPI.io, in the same "standard shape" pattern as the MLB Stats API
  fetcher.
- **Live data is saved to PostgreSQL** —
  `backend/scripts/save_live_data.py` fetches today's games and current
  moneyline odds, then saves them into the database (upserting games,
  inserting new odds snapshots each run).
- **Read-only FastAPI backend** — `backend/main.py` wires together a small
  FastAPI app (`backend/db.py` for the database connection, plus routers in
  `backend/routers/`) with 4 working endpoints, all reading from
  PostgreSQL:
  - `GET /health` — returns `{"status": "ok"}`
  - `GET /games/today` — today's games (joins `games` + `teams`, plus
    `starting_pitchers` if available). Now also returns `game_time`
    (HH:MM, UTC).
  - `GET /odds/latest` — latest moneyline odds per game/team/sportsbook
    from `odds_history`
  - `GET /teams` — all 30 teams
  CORS is enabled for `http://localhost:3000` (GET only) so the Next.js
  dashboard can call it from the browser. No write endpoints, no
  authentication, no cloud deployment — this is a local, read-only API.
- **Next.js dashboard (frontend/)** — a Next.js 16 app (TypeScript, App
  Router, ESLint, no Tailwind) with one page: the homepage. It fetches
  `GET /games/today` and shows a table of today's games (Away Team, Home
  Team, Game Time, Status), with loading, error, and empty states.

---

## 2. What Has Been Verified With Real Live Data

All of the items below have been **run for real** — either against live
data, a real local database, or both — not just written and assumed to
work.

- ✅ `backend/test_mlb_stats_api.py` — printed 15 real MLB games for the day,
  plus team standings (wins/losses), with no API key required.
- ✅ `backend/test_odds_api.py` — printed real moneyline odds for real MLB
  games, from two real sportsbooks (Bet365 and DraftKings). Example of what
  it printed:

  ```
  NY Yankees @ Cleveland  (2026-06-10T17:10:00Z)
    Bet365       NY Yankees: 1.95 (-105)    Cleveland: 1.86 (-116)
    DraftKings   NY Yankees: 1.98 (-102)    Cleveland: 1.84 (-119)
  ```

- ✅ `backend/test_odds_fetcher.py` — confirmed `fetchers/odds_api_io.py`
  returns the same live odds, but reshaped into the project's standard
  format (clean field names, American + decimal odds, a `recorded_at`
  timestamp). Example of what it printed:

  ```
  NY Yankees @ Cleveland   2026-06-10T17:10:00Z
    Sportsbook: Bet365
    Away ML: 1.95 (-105)
    Home ML: 1.86 (-116)
    event_id: 63303615
    recorded_at: 2026-06-10T07:24:55Z
  ```

- ✅ `backend/scripts/test_db_connection.py` — connected to the local
  PostgreSQL database and printed the server's current time, confirming
  `DATABASE_URL` in `backend/.env` is correct.

- ✅ `backend/scripts/save_live_data.py` — fetched real live data and saved
  it into the `mlb_betting_edge` database:
  - **30 teams** saved to `teams`
  - **15 games** saved to `games` (for 2026-06-12)
  - **14 odds rows** saved to `odds_history`, from Bet365 and DraftKings

The PostgreSQL database is fully set up and working end to end.

- ✅ FastAPI backend — started with `uvicorn` and tested live against the
  real `mlb_betting_edge` database:
  - `GET /health` → `{"status": "ok"}`
  - `GET /games/today` → 10 games for 2026-06-12
  - `GET /odds/latest` → 28 odds rows (14 `odds_history` rows × home/away)
  - `GET /teams` → 30 teams

The FastAPI backend is fully working and read-only.

- ✅ `/games/today` UTC-date fix — `backend/routers/games.py` now filters
  on `datetime.now(timezone.utc).date()` instead of `date.today()`.
  Re-tested with `uvicorn --reload` (after also fixing `.env` loading in
  `backend/db.py` — see section 5): still returns 10 games for
  2026-06-12, and `/health`, `/teams`, and `/odds/latest` all still work.

- ✅ **Dashboard MVP — full stack, end to end (2026-06-15).** With FastAPI
  running on port 8000 and `npm run dev` running on port 3000:
  - Ran `backend/scripts/save_live_data.py` — saved 10 games + 13 odds
    rows for 2026-06-15.
  - `GET /games/today` returned 4 games for 2026-06-15 (the other 6 of
    the 10 saved had `game_date = 2026-06-16` — a UTC rollover bug, fixed
    later the same day, see "Game Dates Normalized to MLB Schedule Date"
    in section 5).
  - Opened `http://localhost:3000` in a real browser (headless Chromium
    via Playwright): the homepage showed "MLB Betting Edge" /
    "Today's MLB Games" and a table with all 4 games (Away Team, Home
    Team, Game Time in UTC, Status), no console errors.
  - Also confirmed the **empty state** ("No games scheduled for today.")
    by loading the page before `save_live_data.py` had been run for
    2026-06-15 (when `/games/today` returned `[]`).
  - **Update (later on 2026-06-15):** after the game date normalization
    fix and re-running `save_live_data.py`, `GET /games/today` returns
    all **10** games for 2026-06-15, and the dashboard table shows all 10
    rows. See section 5 for details.

---

## 3. Files That Were Created

```
mlb-betting-edge/
├── README.md                      Project overview
├── PROJECT_PLAN.md                The roadmap / checklist (most up-to-date status)
├── MVP_PLAN.md                    What "Version 1" includes and excludes
├── CLAUDE.md                      Instructions for how Claude should work on this project
├── CURRENT_STATUS.md              This file — checkpoint/save point
├── SETUP_GUIDE.md                 How SportsDataIO API keys work (provider is paused)
├── .env.example                   Template showing which secret keys are needed
├── .gitignore                     Tells Git to never save secrets (.env files)
│
├── backend/
│   ├── README.md                  Explains the backend setup and data sources
│   ├── requirements.txt           Python packages — now includes fastapi, uvicorn
│   ├── .env                       Your real, private API keys + DATABASE_URL
│   ├── __init__.py                Makes "backend" importable for uvicorn
│   ├── main.py                    FastAPI app — wires up routers + /health
│   ├── db.py                      get_db_connection() using psycopg2 + DATABASE_URL
│   ├── test_mlb_stats_api.py      Test script — prints live MLB games/standings
│   ├── test_odds_api.py           Test script — raw OddsAPI.io connection check
│   ├── test_odds_fetcher.py       Test script — prints standardized odds data
│   ├── fetchers/
│   │   ├── __init__.py            Makes "fetchers" a Python package
│   │   ├── mlb_stats_api.py       ACTIVE — fetches games/pitchers/records (free)
│   │   ├── odds_api_io.py         ACTIVE — fetches moneyline odds (needs API key)
│   │   └── sportsdataio.py        PAUSED — kept ready, not used right now
│   ├── routers/
│   │   ├── __init__.py            Makes "routers" a Python package
│   │   ├── games.py               GET /games/today
│   │   ├── odds.py                GET /odds/latest
│   │   └── teams.py               GET /teams
│   └── scripts/
│       ├── test_db_connection.py  Connects to PostgreSQL, runs SELECT NOW()
│       └── save_live_data.py      Saves today's games + odds into PostgreSQL
│
├── database/
│   ├── README.md                  Explains each database table in plain language
│   └── schema.sql                 The 5-table schema — installed in mlb_betting_edge
│
├── docs/
│   ├── README.md                  Notes on data sources and API endpoints
│   ├── ODDS_PROVIDER_RESEARCH.md  Comparison of odds providers + recommendation
│   └── ODDS_API_SETUP.md          Step-by-step OddsAPI.io account/key setup
│
└── frontend/                      Next.js 16 app (TypeScript, App Router, ESLint)
    ├── README.md                  Explains the frontend setup
    ├── .env.local                 NEXT_PUBLIC_API_URL=http://localhost:8000 (not committed)
    ├── package.json               Node.js package list
    ├── AGENTS.md / CLAUDE.md      Auto-generated by create-next-app — notes on
    │                              Next.js 16 conventions for AI coding assistants
    └── app/
        ├── layout.tsx             Root layout — page title "MLB Betting Edge"
        ├── page.tsx               Homepage — fetches /games/today, shows games table
        └── globals.css            Global styles (plain CSS, no Tailwind)
```

A git repository was also initialized at the project root (`git init`) — no
commits made yet, `.gitignore` was already in place.

---

## 4. What APIs Are Active

| API | Status | API Key Needed? | What It's Used For |
|---|---|---|---|
| **MLB Stats API** (statsapi.mlb.com) | ✅ Active | No | Today's games, scores, starting pitchers, team records |
| **OddsAPI.io** (odds-api.io) | ✅ Active | Yes (in `backend/.env`) | Moneyline odds (who's favored, by how much) |
| **SportsDataIO** | ⏸ Paused | Yes (placeholder only) | Not used. Code is ready in `backend/fetchers/sportsdataio.py` if needed later. |

---

## 5. API Quirks We Discovered

These are things that **weren't obvious from the docs** and took some
trial-and-error to figure out. Worth remembering so we don't waste time
re-discovering them later.

### MLB Stats API
- Player names with accents (like "Julio Rodríguez") need a small fix —
  `sys.stdout.reconfigure(encoding="utf-8")` — or Windows terminals show
  garbled characters.

### OddsAPI.io
- The sport is called `baseball`, **not** `mlb`. MLB is a *league* inside
  the `baseball` sport, with the slug `usa-mlb`.
  - Correct: `sport=baseball&league=usa-mlb`
  - Wrong: `sport=mlb` (returns an error)
- Getting odds for a game **requires** a `bookmakers` parameter — you must
  say which sportsbook(s) you want odds from.
- The free plan only allows **2 sportsbooks total**, and it locks in the
  first 2 you ask for. This account is locked to **Bet365** and
  **DraftKings**. (There's a way to reset this if we ever needed different
  books, but we don't need to.)
- Bookmaker names are **case-sensitive** — `"Bet365"` works, `"bet365"`
  does not.
- The odds data comes back as a "dictionary" (a labeled box) where each
  sportsbook name points to a list of betting markets — not a simple list.
- Not every game has odds posted yet, even if the game is upcoming. Some
  games show "no odds posted yet" — that's normal, not a bug. Sportsbooks
  post lines closer to game time.

### PostgreSQL / Local Setup

- The `psycopg2-binary` version originally pinned in `requirements.txt`
  (2.9.9) has no prebuilt Windows wheel for Python 3.13 — installing it
  tries to compile from source and fails without Microsoft C++ Build
  Tools. Fixed by using `psycopg2-binary==2.9.12`, which has a `cp313`
  wheel.
- The MLB Stats API uses the abbreviation **`AZ`** for the Arizona
  Diamondbacks, not `ARI`. The team name lookup in
  `backend/scripts/save_live_data.py` was written with `ARI` first, which
  caused Arizona to be saved with a placeholder name — fixed by using `AZ`.

### Game Dates Are UTC, Not Local — FIXED (2026-06-12)

- `games.game_date` comes from the MLB Stats API's `gameDate` field, which
  is a UTC timestamp split into date + time. Night games starting after
  about 8 PM ET fall after midnight UTC, so their `game_date` ends up as
  the *next* calendar day.
- Example: of the 15 games saved for 2026-06-12, 10 have
  `game_date = 2026-06-12` and 5 have `game_date = 2026-06-13`.
- `/games/today` used to filter on `date.today()` (the server's local
  date), which could disagree with `game_date` depending on the time of
  day and the server's timezone.
- **Fix:** `backend/routers/games.py` now filters on
  `datetime.now(timezone.utc).date()` — an explicit UTC date, matching how
  `game_date` itself is computed. "Today" in the API is now consistent no
  matter what timezone the server runs in.
- This does **not** change which games are grouped together — the 5
  late-night games still have `game_date` one day ahead. That's a deeper
  "schedule date vs. UTC date" question to revisit later if it matters for
  the dashboard.

### Game Dates Normalized to MLB Schedule Date — FIXED (2026-06-15)

The fix above only changed *which* UTC date `/games/today` compared
against — it didn't change how `game_date` itself was computed, so a
single MLB schedule day could still be split across two different
`game_date` values in the database.

**Root cause:** The MLB Stats API's `/schedule` response groups all of a
day's games under `dates[].date` (the schedule date, e.g. `"2026-06-15"`),
but each game's own `gameDate` field is a UTC start timestamp. Night games
starting around 8 PM ET or later cross midnight UTC and land on the *next*
calendar day. The old `_normalize_game()` set `game_date` by splitting
`gameDate` on `"T"` (the UTC date) instead of using the schedule date.

**Example — the 2026-06-15 slate (10 games total):**
- 4 games kept `game_date = 2026-06-15` (gameDate also UTC `06-15`):
  MIA@PHI, KC@WSH, NYM@CIN, SD@STL
- 6 games were saved with `game_date = 2026-06-16` (gameDate UTC `06-16`,
  e.g. `2026-06-16T01:40:00Z`), even though MLB schedules them as part of
  the same 2026-06-15 slate: COL@CHC, MIN@TEX, DET@HOU, LAA@AZ, PIT@ATH,
  TB@LAD

That 4/6 split is exactly why `/games/today` only returned 4 games earlier
on 2026-06-15 (see the Dashboard MVP entry in section 2).

**Fix (ingestion only — no frontend changes):**
- `backend/fetchers/mlb_stats_api.py` — `get_todays_games()` now reads
  `schedule_date = dates[].date` for each date group and passes it into
  `_normalize_game()`, which uses it as `game_date`. `game_time` still
  comes from `gameDate`'s UTC time-of-day (unchanged).
- `backend/scripts/save_live_data.py`:
  - `save_games()`'s `ON CONFLICT (external_game_id) DO UPDATE SET` now
    also updates `game_date` and `game_time`, so re-running the script
    corrects rows that were already saved with the old, wrong `game_date`.
  - `find_matching_game()` now matches an odds record if its UTC date
    equals either the game's `game_date` or `game_date + 1 day`, since
    `game_date` is now the schedule date but OddsAPI.io's event dates are
    still UTC-based.

**Verification (2026-06-15):**
- Before: `games` table had 4 rows with `game_date = 2026-06-15` and 6
  rows with `game_date = 2026-06-16` for this slate.
- Re-ran `python scripts/save_live_data.py` → `Saved 10 games`,
  `Saved 13 odds rows` (all 13 matched a game, none skipped).
- After: all 10 rows for this slate now have `game_date = 2026-06-15`;
  `game_date = 2026-06-16` no longer appears for this slate.
- `GET /games/today` now returns all **10** games for 2026-06-15.
- Dashboard (`http://localhost:3000`) now shows all 10 rows in the games
  table (checked with a headless browser).

**Remaining known issue:** `/games/today` (`backend/routers/games.py`)
still filters on `datetime.now(timezone.utc).date()`. `game_date` is now
the MLB *schedule* date, which is US-centric. For a window right after UTC
midnight (roughly 8 PM–midnight US Eastern), the UTC date is already one
day ahead of the current MLB schedule date, so `/games/today` could
return 0 games even though that schedule day's games are still in
progress. Not addressed here since this fix was scoped to ingestion
only — revisit `backend/routers/games.py` if this becomes a problem.

### CORS Had To Be Enabled For The Dashboard (2026-06-15)

- The browser blocked the Next.js dashboard's `fetch("/games/today")`
  call with a CORS error ("No 'Access-Control-Allow-Origin' header"),
  even though `curl` worked fine — browsers enforce CORS, command-line
  tools don't.
- **Fix:** `backend/main.py` now adds `CORSMiddleware`, allowing GET
  requests from `http://localhost:3000`.

### `/games/today` Now Returns `game_time` (2026-06-15)

- The `games` table already had a `game_time` column (`"HH:MM"`, UTC),
  but `backend/routers/games.py` wasn't selecting or returning it.
- The dashboard needs a "Game Time" column, so the SELECT and the
  response dict in `backend/routers/games.py` now include `game_time`.
  This is not a schema change — the column already existed and was
  already being saved by `save_live_data.py`.

### .env Loading Fixed for `--reload` Mode

- `backend/db.py` called `load_dotenv()` with no path. This worked when
  running uvicorn normally, but failed (`DATABASE_URL` came back `None`,
  causing "no password supplied" errors) when running
  `uvicorn backend.main:app --reload`, because the reloader's subprocess
  broke `python-dotenv`'s automatic file discovery.
- **Fix:** `backend/db.py` now calls
  `load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))` — an
  explicit path based on the file's own location, so it works the same in
  both normal and `--reload` mode.

---

## 6. What Is Still Not Built

- ❌ Only one frontend page exists (the homepage / today's games table) —
  no matchups, props, line movement, or parlay pages yet.
- ❌ No write endpoints, authentication, or cloud deployment — the FastAPI
  backend is local and read-only by design (for now).
- ❌ `starting_pitchers` and `team_records` tables exist but are empty —
  `save_live_data.py` currently saves `teams`, `games`, and `odds_history`
  only, so `probable_home_pitcher`/`probable_away_pitcher` in
  `/games/today` are always `null` right now.
- ❌ No line movement *view* yet — `odds_history` now collects a new
  snapshot each time `save_live_data.py` runs, but there's no query or
  chart yet to look at how odds have moved over time.

---

## 7. Exact Commands to Run

Both commands below assume you're starting from the project root folder
(`mlb-betting-edge/`).

### MLB Stats API Test (games, scores, standings — no key needed)

```
cd backend
.\venv\Scripts\activate
python test_mlb_stats_api.py
```

**What you should see:** A list of today's MLB games with teams, scores
(if started), and starting pitchers, followed by team standings.

### OddsAPI.io Test (raw connection check)

```
cd backend
.\venv\Scripts\activate
python test_odds_api.py
```

**What you should see:** A list of upcoming MLB games, with moneyline odds
from Bet365 and DraftKings for any games that have odds posted yet.

### OddsAPI.io Fetcher Test (standardized data)

```
cd backend
.\venv\Scripts\activate
python test_odds_fetcher.py
```

**What you should see:** The same live odds, but reshaped into the
project's standard format — clean field names, American + decimal odds,
and a `recorded_at` timestamp. This is the format the database will
eventually store.

> If you ever see "API key not set" or "401 Unauthorized," check that
> `backend/.env` has a real `ODDS_API_KEY` value (see
> `docs/ODDS_API_SETUP.md`).

### Database Connection Test

```
cd backend
.\venv\Scripts\activate
python scripts/test_db_connection.py
```

**What you should see:** `SUCCESS: Connected to PostgreSQL` plus the
database server's current time.

### Save Live Data (games + odds → PostgreSQL)

```
cd backend
.\venv\Scripts\activate
python scripts/save_live_data.py
```

**What you should see:** Counts of games/odds fetched and saved, e.g.
`Saved 15 games` and `Saved 14 odds rows`.

### Check the Database Directly

```
$env:PGPASSWORD = "<your postgres password from backend/.env>"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d mlb_betting_edge -c "\dt"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d mlb_betting_edge -c "SELECT COUNT(*) FROM games;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d mlb_betting_edge -c "SELECT COUNT(*) FROM odds_history;"
```

### Run the FastAPI Backend

```
cd C:\Users\rich-\RICH-LABS\mlb-betting-edge
.\backend\venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

> Note: `.\backend\venv\Scripts\activate` may be blocked by PowerShell's
> execution policy. Calling `python.exe` directly from the venv works
> without needing to activate it.

**What you should see:** `Uvicorn running on http://127.0.0.1:8000`

Then open in a browser (or use `Invoke-RestMethod` in PowerShell):
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/games/today
- http://127.0.0.1:8000/odds/latest
- http://127.0.0.1:8000/teams

### Run the Next.js Dashboard

```
cd frontend
npm run dev
```

**What you should see:** `Local: http://localhost:3000`

Open http://localhost:3000 in a browser. The FastAPI backend (above) must
also be running, since the homepage fetches `/games/today` from it.

---

## 8. Next Recommended Step

**Dashboard MVP homepage is done and verified.** Possible next steps
(pick one, per `CLAUDE.md` — one feature at a time):

- Show real game times in a friendlier format (e.g. local time instead of
  raw UTC "HH:MM").
- Add `/odds/latest` data to the dashboard (e.g. a moneyline column).
- Build a second page (matchups, line movement, etc.) per
  `PROJECT_PLAN.md` Phase 3.

---

## 9. When We Need Cloud Hosting

**Short answer: not yet.** Everything so far runs fine on your local PC,
and that's exactly where it should stay for now.

### Why local is fine right now

Your computer can run Python scripts, a local PostgreSQL database, and a
local Next.js website just as well as any cloud service can — for free,
with no setup. Cloud hosting only starts to matter once the project needs
to do something your PC *can't* do, which is run **24/7 even when you're
not at your computer**.

### When cloud becomes necessary

Right now, every script in this project only runs when **you** type a
command. That's perfect for testing.

Cloud hosting becomes necessary once we want the project to run **on its
own, automatically, all the time** — specifically:

- **Scheduled odds pulls** — automatically checking OddsAPI.io every
  15-30 minutes, 24/7, to track how odds move before each game (this is
  what fills the `odds_history` table and powers line movement charts).
- **Simulations / analysis running automatically** — any future feature
  that needs to recalculate things on a schedule, without you manually
  running a script.

A laptop that's turned off, asleep, or closed can't do either of those —
so this is the point where moving to the cloud actually solves a real
problem, instead of just adding complexity for no reason.

### Target cloud stack (when the time comes)

| Piece | Where It Goes | What It Replaces |
|---|---|---|
| Database | **Supabase** (managed PostgreSQL) | Your local PostgreSQL database |
| Scheduled backend jobs | **Railway** | You manually running fetcher scripts |
| Frontend (dashboard website) | **Vercel** | Running `npm run dev` locally |

This matches the stack already listed in `CLAUDE.md` — nothing new to
decide later, just a matter of *when* to set it up.

### The trigger point

We'll move to cloud hosting once **both** of these are true:

1. Games and odds are being **saved to the database successfully**
   (Step 4/5 territory — fetchers write to PostgreSQL, not just print).
2. We want those fetchers to run **24/7 automatically**, so odds history
   keeps building up even when your PC is off.

Until both of those are true, staying local keeps things simple, free, and
easy to debug — exactly what we want during development.
