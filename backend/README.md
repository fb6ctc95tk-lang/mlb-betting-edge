# Backend

Python code that fetches MLB data and (later) serves it to the frontend.

---

## Data Sources

| Data we need              | Source                  | Cost  | Status     |
|----------------------------|-------------------------|-------|------------|
| Games, scores, status       | MLB Stats API           | Free, no key | **Active** |
| Starting pitchers           | MLB Stats API           | Free, no key | **Active** |
| Team records (standings)    | MLB Stats API           | Free, no key | **Active** |
| Moneyline odds / line movement | OddsAPI.io           | Free tier (2 sportsbooks) | **Active** |
| SportsDataIO (any data)     | SportsDataIO            | Paid (after free trial) | **Paused** |

We're building Version 1 on the **free MLB Stats API** for games/pitchers/
records, and **OddsAPI.io** (free tier) for moneyline odds. SportsDataIO is
paused but kept ready in `fetchers/sportsdataio.py` in case we need it later.

---

## The Fetcher Pattern (why this is "flexible")

Every file in `fetchers/` is a **translator**. Each provider (MLB Stats API,
SportsDataIO, etc.) returns data in its own messy, provider-specific format.
Each fetcher's job is to convert that into one **standard shape** —
the same field names every time, no matter the source.

```
MLB Stats API  ──┐
                  ├──► fetchers/*.py ──► STANDARD SHAPE ──► database / FastAPI
SportsDataIO   ──┘
```

The database code and API routes (built in later steps) will only ever
work with the standard shape. That means:

- Swapping providers = write one new fetcher file. Nothing else changes.
- Using two providers at once (e.g. games from MLB Stats API, odds from
  somewhere else) just means calling two fetchers — both hand back data
  in the same shape.

The exact shape is documented at the top of `fetchers/mlb_stats_api.py`.

---

## Current Files

```
backend/
├── fetchers/
│   ├── __init__.py
│   ├── mlb_stats_api.py   # ACTIVE — free, no key needed
│   ├── odds_api_io.py     # ACTIVE — needs ODDS_API_KEY (moneyline odds)
│   └── sportsdataio.py    # PAUSED — needs API key, kept for later
├── test_mlb_stats_api.py  # run this to see live games/standings
├── test_odds_api.py       # run this to see raw OddsAPI.io connection test
├── test_odds_fetcher.py   # run this to see standardized odds data
├── .env                   # your real API keys (never shared)
├── requirements.txt
└── README.md
```

---

## First-Time Setup

### Step 1 — Make sure Python is installed

```
python --version
```

You should see `Python 3.11` or higher.

---

### Step 2 — Create a virtual environment (one time only)

A virtual environment is an isolated box for this project's Python packages.

```
cd mlb-betting-edge/backend
python -m venv venv
```

---

### Step 3 — Activate the virtual environment

Do this every time you open a new terminal.

**Windows (PowerShell):**
```
venv\Scripts\Activate.ps1
```

**Mac/Linux:**
```
source venv/bin/activate
```

When active, your prompt shows `(venv)` at the start.

---

### Step 4 — Install packages

```
pip install -r requirements.txt
```

---

### Step 5 — Run the test script

No `.env` file. No API key. Just run it:

```
python test_mlb_stats_api.py
```

---

## What Success Looks Like

```
============================================================
  Today's MLB Games  (MLB Stats API — free, no key needed)
============================================================

  1. BOS @ TB   17:10 UTC   [scheduled]
     Pitchers: Jake Bennett  vs  Drew Rasmussen

  2. NYY @ CLE   17:10 UTC   [scheduled]
     Pitchers: Carlos Rodón  vs  Parker Messick
  ...

============================================================
  Team Records (first 5 shown)
============================================================
  TB    39-25    Home: 23-9   Away: 16-16
  NYY   40-26    Home: 19-12   Away: 21-14
  ...

============================================================
  Connection successful! No API key was needed.
============================================================
```

---

## OddsAPI.io (Active — Moneyline Odds)

`fetchers/odds_api_io.py` fetches moneyline odds from two sportsbooks
(Bet365 and DraftKings — that's what the free tier locks you into).

**Setup (one time):**
1. Follow `docs/ODDS_API_SETUP.md` to get a free API key
2. Create `backend/.env` from `.env.example` (if you haven't already)
3. Set `ODDS_API_KEY` in that file

**Run the fetcher test:**
```
python test_odds_fetcher.py
```

**What success looks like:**
```
============================================================
  Standardized Moneyline Odds (odds_api_io fetcher)
============================================================

  NY Yankees @ Cleveland   2026-06-10T17:10:00Z
    Sportsbook: Bet365
    Away ML: 1.95 (-105)
    Home ML: 1.86 (-116)
    event_id: 63303615
    recorded_at: 2026-06-10T07:24:55Z
  ...

============================================================
  Fetcher returned 4 odds record(s).
============================================================
```

The standard shape (`event_id`, `home_team`, `away_team`, `game_time`,
`sportsbook`, moneyline odds in both decimal and American formats, and
`recorded_at`) is documented at the top of `fetchers/odds_api_io.py`.

A game with no posted odds yet just won't appear — that's normal, not an
error.

---

## SportsDataIO (Paused)

`fetchers/sportsdataio.py` is fully written but not used. To activate it later:

1. Follow `SETUP_GUIDE.md` to get an API key
2. Create `backend/.env` from `.env.example`
3. Set `SPORTSDATAIO_API_KEY` in that file
4. Call `sportsdataio.get_todays_games()` — it returns the same shape as
   `mlb_stats_api.get_todays_games()`, so it's a drop-in option

---

## Common Errors and Fixes

| Error message               | What it means               | Fix                                      |
|------------------------------|-----------------------------|--------------------------------------------|
| `ModuleNotFoundError: requests` | Packages not installed   | Run `pip install -r requirements.txt`    |
| `(venv)` not in prompt        | Virtual env not active      | Run the activate command in Step 3       |
| Connection / timeout error    | No internet or API is down  | Check your connection, try again         |
