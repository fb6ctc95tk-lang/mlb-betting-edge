# Current Status — MLB Betting Edge

**Last updated:** 2026-07-14
**Current Phase:** Phase 13 Active — Research Layer + Market Research Board + Totals Investigation Pending

This file is a "save point" for the project. If you take a break and come
back later (or open a new chat with Claude Code), read this file first —
it explains exactly what's working, what's been tested, and what to do next.

---

## 1. What Currently Works

### Database
- **PostgreSQL 17.10** running locally. Database `mlb_betting_edge` has 5 tables:
  `teams`, `games`, `starting_pitchers`, `odds_history`, `team_records`.
- All 30 MLB teams are seeded.

### Data Ingestion
- `backend/scripts/save_live_data.py` fetches and saves:
  - Today's games (from MLB Stats API — free, no key)
  - Probable starting pitchers (from MLB Stats API)
  - Team win/loss records (from MLB Stats API)
  - Moneyline odds — Bet365 + DraftKings (from OddsAPI.io — requires API key)
  - Injury reports (from ESPN — free, no key)
  - Bullpen context — innings pitched in previous game per team (from MLB Stats API)
  - Weather at stadium — temperature, wind, precipitation chance (from Open-Meteo — free, no key)
- Accepts an optional `--date YYYY-MM-DD` flag for backfilling historical data.
- `backend/scripts/run_ingestion.bat` wraps the above script for Task Scheduler:
  writes a timestamped start/end block with exit code to `logs/ingestion.log`.

### Automated Daily Ingestion (as of 2026-07-12)
- Two Windows Task Scheduler tasks are registered and active:
  - **"MLB Ingestion 11AM"** — runs daily at 11:00 AM, captures morning lines
  - **"MLB Ingestion 7PM"** — runs daily at 7:00 PM, captures pre-game/closing lines
- Both are configured: user `rich-`, logon mode `Interactive only`, enabled.
- The 11 AM task was verified with a live test run on 2026-07-12 (exit=0, 15 games saved).
- Next scheduled runs: 2026-07-13 at 11:00 AM and 7:00 PM.
- Log file: `logs/ingestion.log` — each run appends a timestamped START/END block.

### FastAPI Backend
`backend/main.py` runs a read-only FastAPI app on port 8000. All endpoints
read from PostgreSQL. CORS is enabled for `http://localhost:3000`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Returns `{"status": "ok"}` |
| `GET /research/today` | Full research payload for today's games (single call for all data) |
| `GET /research/date/{date}` | Same payload for any historically stored date |
| `GET /research/available-dates` | All distinct stored game dates, newest first |
| `GET /research/game/{game_id}` | Full research detail for a single game |
| `GET /games/today` | Raw game list (no research data) |
| `GET /odds/movement` | Line movement with optional filters |
| `GET /teams` | All 30 MLB teams |

The `/research/*` endpoints return per-game objects with:
- Game metadata (id, date, time, status, teams, pitchers, records)
- `odds[]` — latest moneyline per sportsbook + implied probability
- `line_movement[]` — opening vs latest per sportsbook/side, with delta
- `away_team_form` / `home_team_form` — last-10 record + run differential
- `away_team_streak` / `home_team_streak` — current win/loss streak
- `away_team_splits` / `home_team_splits` — road record / home record
- `weather` — temperature, wind speed/direction, precipitation chance
- `away_injuries[]` / `home_injuries[]` — player name, status, description
- `away_bullpen` / `home_bullpen` — innings pitched last game + date

### Next.js Dashboard (frontend/)
A Next.js app (TypeScript, App Router, ESLint, no Tailwind) at `http://localhost:3000`.
Two pages:

**Homepage (`/`)**
- Date selector (dropdown populated from `/research/available-dates`) —
  defaults to Today, or loads any stored date; includes "Back to Today" button.
- Ingestion Status Card — shows last run time and exit code from `logs/ingestion.log`.
- Data Quality Card — flags missing odds, games, weather, or bullpen data.
- Filter bar — three checkboxes: Has Injuries, Has Significant Line Movement,
  Has Weather Context. All filters are additive (AND logic).
- Sort — Default (game time order) or Largest Line Movement.
- Flag Summary — shows count of flagged games (injuries / line movement / weather)
  for the current filtered view.
- Research Workspace — pin any game(s) to a persistent workspace (saved in
  `localStorage`). Workspace persists across page reloads.
  - Per-game notes textarea (up to 1000 characters, also persisted in `localStorage`).
  - Side-by-side comparison table when 2 workspace games are selected:
    compares research flags, records, pitchers, last-10 form, streaks,
    splits, weather, bullpen load, injuries, moneylines, and max line move.
- Games table — 25 columns showing all research context per game:
  Detail (View link + Workspace button), Flags, Away/Home teams,
  Game Time (UTC), Status, Away/Home Pitcher, Away/Home Record,
  Away/Home Streak, Away Road Record, Home Home Record, Away/Home Last 10,
  Bet365 Moneyline, Bet365 Implied Prob, DraftKings Moneyline,
  DraftKings Implied Prob, Weather, Away Injuries, Home Injuries,
  Away Bullpen, Home Bullpen.
- Line Movement table — all movement rows for the current filtered/sorted view:
  opening ML, latest ML, delta (color-coded green/red), timestamps.
- Research Flags on each game row (emoji badges: ⚠ injuries, 📈 line movement,
  🌬 weather).

**Game Detail (`/game/[game_id]`)**
- Dedicated research view for a single game.
- Shows full matchup: pitchers, records, streaks, splits, form, weather,
  injuries, bullpen, odds, and line movement for that game only.
- Linked from the games table "View" column and from the workspace.
- Research Insights panel: displays all generated insights for the game
  (form vs. market divergence, record vs. recent form divergence).

**Market Research Board (`/opportunities`)**
- Lists Market Opportunities across all games for a selected date.
- Date selector mirrors the homepage pattern: defaults to Today, supports
  any stored historical date, "Back to Today" button.
- Fetches from `GET /research/today` or `GET /research/date/{date}` —
  same data source as the homepage.
- Each card shows: game matchup, market type (`FULL_GAME_MONEYLINE`),
  opportunity title, summary, reasons, caution notes, and source insights.
- No EV, no fair odds, no confidence ratings, no betting recommendations.
- All opportunity language is neutral and research-oriented.

### Research Layer (frontend/lib/)
All three modules are pure TypeScript — no backend, no database changes.

**`researchInsights.ts`** — insight generators
- `InsightableGame` structural type: game object with optional form/odds/record fields.
- `getResearchInsights(game)` — runs all generators, returns flat `ResearchInsight[]`.
- **Generator 1 — Form vs. Market Divergence** (`form-market-divergence`):
  fires when a hot team (≥65% last-N win rate) is priced as a significant
  underdog (≤42% implied), or a cold team (≤35%) is priced as a heavy
  favorite (≥58%).
- **Generator 2 — Record vs. Recent Form Divergence**
  (`record-form-divergence-{away|home}-{up|down}`):
  fires when recent win rate diverges from season win rate by ≥15 percentage
  points. Independent per team (up to two insights per game).
- Minimum sample: 5 games for any form-based insight.
- No betting language. No Market Opportunity mapping in this layer.

**`marketOpportunities.ts`** — opportunity generators
- `MarketType = "FULL_GAME_MONEYLINE"` — only supported type.
- `MarketOpportunity` type: `{ id, gameId, marketType, title, summary,
  reasons[], cautionNotes[], sourceInsightIds[], displayPriority? }`.
  No `direction`, `team`, or `confidence` fields.
- **Generator — Form Divergence to Moneyline**: fires on `form-market-divergence`
  insight ID; produces one `FULL_GAME_MONEYLINE` opportunity per trigger.
- `getMarketOpportunities(game, insights)` — runs all generators.

**`marketResearchBoard.ts`** — board data helper
- `getBoardResearchUrl(apiBase, selectedDate)` — pure URL helper; returns
  `/research/today` or `/research/date/{date}`; exported for testing.
- `getMarketOpportunitiesForBoard(games)` — maps all games through insight
  and opportunity generators, returns flattened board entries.

### Shared Frontend Logic (frontend/lib/)
- `gameFilters.ts` — `applyFilters()` applies the three checkbox filters;
  exports `LINE_MOVE_THRESHOLD` constant (used by flags and filters to
  define "significant" movement).
- `gameFlags.ts` — `getGameFlags()` derives emoji flag badges from a game object.
- `gameFlagSummary.ts` — `getGameFlagSummary()` counts flagged games across
  the full displayed list.

### Components (frontend/components/)
- `ResearchFlags.tsx` — reusable badge renderer used in both the game table
  and the comparison view.

### Frontend Components (frontend/app/components/)
- `IngestionStatusCard.tsx` — reads `/health/ingestion` (or similar) and
  shows last run time + status.
- `DataQualityCard.tsx` — reads `/health/data-quality` and shows data
  completeness warnings.

### Test Coverage
- **Backend** — 50 pytest tests across 7 modules:
  `test_research_endpoints.py`, `test_weather.py`, `test_injuries.py`,
  `test_bullpen.py`, `test_data_quality.py`, `test_game_detail.py`,
  `test_health_ingestion.py`. All pass. Tests hit real local PostgreSQL — no mocks.
- **Frontend** — 107 Vitest tests across 6 modules:
  `gameFilters.test.ts`, `gameFlags.test.ts`, `gameFlagSummary.test.ts`,
  `researchInsights.test.ts` (42 tests),
  `marketOpportunities.test.ts` (14 tests),
  `marketResearchBoard.test.ts` (17 tests). All pass.

---

## 2. What Has Been Verified With Real Live Data

- ✅ MLB Stats API — games, pitchers, team records fetched and saved live.
- ✅ OddsAPI.io — Bet365 + DraftKings moneyline odds fetched and saved live.
- ✅ ESPN injury feed — injury reports parsed and saved live.
- ✅ Open-Meteo weather — temperature, wind, precipitation fetched per stadium.
- ✅ Bullpen context — innings from previous game computed per team.
- ✅ PostgreSQL end-to-end — all 5 tables populated via `save_live_data.py`.
- ✅ FastAPI backend — all endpoints tested against real data.
- ✅ Dashboard — homepage renders all 25 columns correctly with live data.
- ✅ Game detail page — renders full research context for a single game.
- ✅ Research Insights panel — form-market-divergence and record-form-divergence
  insights render on `/game/211` (NYM exceeds season profile, ATL trails season profile).
- ✅ Market Research Board — `/opportunities` loads, historical date selector works,
  2026-06-19 renders a valid board entry; no EV/confidence/recommendations present.
- ✅ Research workspace — add/remove games, notes persist in localStorage.
- ✅ Comparison view — side-by-side table renders correctly for 2 workspace games.
- ✅ Research flags — injury/line movement/weather badges appear on correct games.
- ✅ Filters and sort — checkboxes and sort dropdown filter/reorder the game list correctly.
- ✅ Date selector (homepage and board) — dropdown populates from API, historical dates load.
- ✅ Task Scheduler — `schtasks /run` test on 2026-07-12 produced exit=0, 15 games saved,
  log entry written correctly.
- ✅ All 157 automated tests pass (50 backend + 107 frontend).
- ✅ TypeScript passes with 0 errors.
- ✅ ESLint passes with 0 warnings.
- ⚠ OddsAPI.io totals market: STILL INCONCLUSIVE — all diagnostic runs fell during
  the MLB All-Star break when no games were scheduled. Recheck required.

---

## 3. Files That Were Created

```
mlb-betting-edge/
├── README.md
├── PROJECT_PLAN.md
├── MVP_PLAN.md
├── CLAUDE.md
├── CURRENT_STATUS.md              (this file)
├── PROJECT_STATUS.md
├── APP_ARCHITECTURE.md
├── SETUP_GUIDE.md
├── POSTGRES_SETUP.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── logs/
│   └── ingestion.log              Appended by run_ingestion.bat each run
│
├── backend/
│   ├── .env                       DATABASE_URL + ODDS_API_KEY (not committed)
│   ├── main.py                    FastAPI app entry point
│   ├── db.py                      get_db_connection() — explicit .env path
│   ├── odds_math.py               american_odds_to_implied_probability()
│   ├── fetchers/
│   │   ├── mlb_stats_api.py       Games, pitchers, records, bullpen (free)
│   │   ├── odds_api_io.py         Moneyline odds — Bet365 + DraftKings
│   │   ├── injuries.py            ESPN injury feed (free)
│   │   ├── weather.py             Open-Meteo weather + stadium coordinates (free)
│   │   └── sportsdataio.py        PAUSED — kept ready, not used
│   ├── routers/
│   │   ├── games.py               /games/today, /game/{id}
│   │   ├── odds.py                /odds/latest, /odds/today, /odds/movement
│   │   ├── research.py            /research/today, /research/date/{date},
│   │   │                          /research/available-dates
│   │   ├── health.py              /health, /health/ingestion, /health/data-quality
│   │   └── teams.py               /teams
│   ├── scripts/
│   │   ├── save_live_data.py      Daily ingestion (accepts --date flag)
│   │   ├── run_ingestion.bat      Task Scheduler wrapper — writes to logs/ingestion.log
│   │   └── diagnostics/
│   │       ├── check_oddsapi_totals.py    OddsAPI.io totals market probe (max 6 requests)
│   │       └── TOTALS_DIAGNOSTIC_RUNBOOK.md   Controlled recheck instructions
│   └── tests/
│       ├── test_research_endpoints.py
│       ├── test_weather.py
│       ├── test_injuries.py
│       ├── test_bullpen.py
│       ├── test_data_quality.py
│       ├── test_game_detail.py
│       └── test_health_ingestion.py
│
├── database/
│   ├── README.md
│   └── schema.sql                 5-table schema
│
├── docs/
│   ├── ODDS_PROVIDER_RESEARCH.md
│   ├── ODDS_API_SETUP.md
│   └── MARKET_RESEARCH_ARCHITECTURE.md   Research layer design + diagnostic log
│
└── frontend/                      Next.js app (TypeScript, App Router, ESLint)
    ├── .env.local                 NEXT_PUBLIC_API_URL=http://localhost:8000
    ├── package.json
    ├── components/
    │   └── ResearchFlags.tsx      Reusable emoji flag badge renderer
    ├── lib/
    │   ├── gameFilters.ts         applyFilters() + LINE_MOVE_THRESHOLD
    │   ├── gameFilters.test.ts
    │   ├── gameFlags.ts           getGameFlags()
    │   ├── gameFlags.test.ts
    │   ├── gameFlagSummary.ts     getGameFlagSummary()
    │   ├── gameFlagSummary.test.ts
    │   ├── researchInsights.ts    InsightableGame, getResearchInsights(), two generators
    │   ├── researchInsights.test.ts
    │   ├── marketOpportunities.ts MarketOpportunity, getMarketOpportunities(), FULL_GAME_MONEYLINE
    │   ├── marketOpportunities.test.ts
    │   ├── marketResearchBoard.ts getBoardResearchUrl(), getMarketOpportunitiesForBoard()
    │   └── marketResearchBoard.test.ts
    └── app/
        ├── layout.tsx
        ├── page.tsx               Homepage (all dashboard features)
        ├── globals.css
        ├── components/
        │   ├── IngestionStatusCard.tsx
        │   └── DataQualityCard.tsx
        ├── game/
        │   └── [game_id]/
        │       └── page.tsx       Game detail research view + Research Insights panel
        └── opportunities/
            └── page.tsx           Market Research Board with historical date selector
```

---

## 4. What APIs Are Active

| API | Status | Key Needed? | What It Provides |
|---|---|---|---|
| MLB Stats API (statsapi.mlb.com) | ✅ Active | No | Games, pitchers, records, bullpen |
| OddsAPI.io (odds-api.io) | ✅ Active | Yes (`backend/.env`) | Bet365 + DraftKings moneylines |
| ESPN (site.api.espn.com) | ✅ Active | No | Injury reports |
| Open-Meteo (api.open-meteo.com) | ✅ Active | No | Stadium weather |
| SportsDataIO | ⏸ Paused | Yes (placeholder) | Not used |

---

## 5. Known Issues and Quirks

### Injury Team Mapping
The ESPN injury feed returns team names that don't always match the
abbreviations used in the `teams` table. As a result, most injury rows are
currently skipped with "unknown team" in the log (e.g., `283 skipped`).
Injuries show as empty in the dashboard for affected teams. This is a known
gap — the injury data fetcher works, but the team-name-to-abbreviation
mapping is incomplete.

### OddsAPI.io Free Tier Constraints
- Sport slug is `baseball`, league is `usa-mlb` — not `sport=mlb`.
- Requires a `bookmakers` parameter.
- Free plan is locked to the first 2 sportsbooks requested: **Bet365** and **DraftKings**.
- Not every game has odds posted; some games show no odds closer to game time —
  this is normal, not a bug.
- Bookmaker names are case-sensitive: `"Bet365"` works, `"bet365"` does not.

### Open-Meteo Occasional 503s
Open-Meteo sometimes returns 503 (Service Unavailable) for individual
stadium lookups. The ingestion script logs these failures and skips those
games, but exits with code 0. Affected games show "Weather unavailable" in
the dashboard. These are transient — the next run typically succeeds.

### Game Dates Are MLB Schedule Dates (Not UTC)
`game_date` in the database is the MLB schedule date (US-local), not the UTC
date. Night games starting after ~8 PM ET fall after midnight UTC, so
their raw `gameDate` from the API would be the next calendar day — but the
ingestion script corrects this by reading the schedule's `dates[].date`
field. The `/games/today` endpoint filters on UTC date, which matches the
schedule date for most of the day but may not match for a brief window
right after midnight UTC (roughly 8–11 PM ET). Not a problem in practice.

### OddsAPI.io Totals Market — INCONCLUSIVE (Phase 13 diagnostic)
Three diagnostic runs were performed to probe whether OddsAPI.io's free tier
returns totals (over/under) data. All runs fell during the MLB All-Star break
(no games scheduled), so every event had empty bookmakers — inconclusive, not
"unavailable." The `markets=totals` parameter returns HTTP 200 (request accepted)
but yields no data when no games are live.

**Recheck condition:** Run only after scheduled ingestion exits with code 0 AND
`logs/ingestion.log` shows `Found N odds records` where N > 0 in the same run.
`Games saved: N` alone is NOT sufficient — odds must be present.

**Diagnostic command (max 6 API requests):**
```
.\backend\venv\Scripts\python.exe .\backend\scripts\diagnostics\check_oddsapi_totals.py
```

**Do not run** outside the controlled diagnostic script. Do not implement totals
storage, schema changes, or production fetcher updates based on this diagnostic.

### Task Scheduler — Interactive Only
Both scheduled tasks run in `Interactive only` logon mode, meaning they
require an active user session. If the PC is asleep or logged out at
11 AM or 7 PM, the task will not run for that day. This is expected for a
local-only setup.

### .env Loading in Reload Mode
`backend/db.py` uses an explicit path: `load_dotenv(os.path.join(
os.path.dirname(__file__), ".env"))`. This is intentional — the standard
`load_dotenv()` with no path breaks when running `uvicorn --reload` because
the reloader subprocess changes the working directory.

---

## 6. What Is Still Not Built

- ❌ No cloud deployment — everything runs locally (Supabase + Railway + Vercel
  are the planned future stack, documented in CLAUDE.md; not needed yet).
- ❌ No write endpoints or authentication.
- ❌ Injury team mapping is incomplete — injury data is fetched but most rows
  are currently skipped at save time due to unknown team names.
- ❌ No prediction model, edge calculations, or betting logic.
- ❌ No push notifications, email alerts, or mobile-optimized layout.
- ⏳ Totals market support — BLOCKED pending valid OddsAPI.io recheck.
  See Phase 13 diagnostic status in Known Issues above.
- ❌ Additional Research Insight generators (bullpen stress, streak pressure,
  road/home form splits, line move vs. form) — planned but not yet built.
- ❌ Additional MarketType values beyond `FULL_GAME_MONEYLINE` — no RunLine,
  Totals, or First-5 markets implemented.

---

## 7. Exact Commands to Run

All commands assume the project root `mlb-betting-edge/` unless noted.

### Run Manual Ingestion (Today)
```
.\backend\venv\Scripts\python.exe .\backend\scripts\save_live_data.py
```

### Backfill a Historical Date
```
.\backend\venv\Scripts\python.exe .\backend\scripts\save_live_data.py --date 2026-07-01
```

### Run Backend Tests
```
.\backend\venv\Scripts\python.exe -m pytest backend/tests/ -v
```

### Run the FastAPI Backend
```
.\backend\venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```
Then open: http://127.0.0.1:8000/health

### Run the Next.js Dashboard
```
cd frontend
npm run dev
```
Then open: http://localhost:3000
(FastAPI must also be running.)

### Run Frontend Tests
```
cd frontend
npm test
```

### Run TypeScript Check
```
cd frontend
npx tsc --noEmit
```

### Check Task Scheduler Tasks
```
schtasks /query /tn "MLB Ingestion 11AM" /fo LIST /v
schtasks /query /tn "MLB Ingestion 7PM" /fo LIST /v
```

### Trigger a Manual Scheduled Run (for testing)
```
schtasks /run /tn "MLB Ingestion 11AM"
```

### Check Database Directly
```powershell
$env:PGPASSWORD = "<your postgres password from backend/.env>"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d mlb_betting_edge -c "SELECT COUNT(*) FROM games;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -d mlb_betting_edge -c "SELECT COUNT(*) FROM odds_history;"
```

---

## 8. Daily Operational Routine

With automation active, the day-to-day workflow is:

1. Open the dashboard (`npm run dev` + `uvicorn`).
2. Check the **Ingestion Status Card** — confirms last run time and exit code.
3. Check the **Data Quality Card** — flags if odds, weather, or games are missing.
4. Use filters to narrow to games with injuries, line movement, or weather context.
5. Add interesting games to the **Research Workspace**.
6. Use the **Comparison View** to compare two shortlisted games side by side.
7. Use the **Game Detail** page for a full breakdown of any single game.
8. Add notes to workspace games as needed.

No manual scripts need to be run on a normal day — the 11 AM and 7 PM tasks
handle ingestion automatically.

---

## 9. When We Need Cloud Hosting

Not yet. Cloud hosting becomes necessary once we want:
- Ingestion running 24/7 regardless of whether the PC is on
- The dashboard accessible from other devices or shared with others

Target stack (when the time comes): Supabase (database), Railway (backend +
scheduled scripts), Vercel (frontend). This matches what's documented in
CLAUDE.md — no new decisions needed, just a matter of when.
