# Setup Guide — MLB Betting Edge

This guide explains how to get the project running locally from scratch.

---

## What You Need

| Requirement | What It Does | Cost |
|---|---|---|
| PostgreSQL | Local database | Free |
| Python 3.11+ | Runs the backend and ingestion scripts | Free |
| Node.js 18+ | Runs the Next.js frontend | Free |
| OddsAPI.io account | Provides Bet365 + DraftKings moneyline odds | Free tier |

Game data (schedule, pitchers, team records) comes from the **official MLB Stats API**, which requires no account and no API key.

---

## 1. PostgreSQL

PostgreSQL stores all game data, odds, and team records.

### Install

Download from: https://www.postgresql.org/download/windows/

During installation:
- Set a password for the `postgres` user — write it down
- Keep the default port (`5432`)
- Keep all default components (PostgreSQL Server, pgAdmin, Command Line Tools)

### Verify

```
psql --version
```

Should print something like `psql (PostgreSQL) 17.x`.

### Create the database

```
psql -U postgres -c "CREATE DATABASE mlb_betting_edge;"
```

### Create the tables

From the repo root:
```
psql -U postgres -d mlb_betting_edge -f database/schema.sql
```

---

## 2. OddsAPI.io API Key

OddsAPI.io provides Bet365 and DraftKings moneyline odds on a permanent free tier (100 requests/hour, no credit card required).

### Get a key

1. Go to https://odds-api.io
2. Create a free account
3. Copy your API key from the dashboard

### Important: sportsbook lock-in

The free tier locks your account to **2 sportsbooks on first use**. This project uses:
- **Bet365**
- **DraftKings**

The first time you call the odds API with these two sportsbook names, your key is locked to them. Do not change the `BOOKMAKERS` value in `fetchers/odds_api_io.py` unless you intend to reset your key.

---

## 3. Environment Variables

The backend reads two variables from `backend/.env`.

Create the file (copy from the example if it exists):

```
backend/.env
```

Contents:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/mlb_betting_edge
ODDS_API_KEY=your_oddsapiio_key_here
```

Replace `YOUR_PASSWORD` with the PostgreSQL password you set during installation, and `your_oddsapiio_key_here` with your real OddsAPI.io key.

**Never commit `.env` to git.** It is already in `.gitignore`.

---

## 4. Backend Setup

### Create a virtual environment (one time)

From the repo root:
```
cd backend
python -m venv venv
```

### Activate the virtual environment

Run this every time you open a new terminal:

**Windows (PowerShell):**
```
backend\venv\Scripts\Activate.ps1
```

Your prompt will show `(venv)` when active.

### Install packages

```
pip install -r backend/requirements.txt
```

### Verify the database connection

```
backend/venv/Scripts/python.exe backend/scripts/test_db_connection.py
```

Should print: `SUCCESS: Connected to PostgreSQL`

### Run the ingestion script

This fetches today's games, pitchers, records, and odds, and saves them to PostgreSQL:

```
backend/venv/Scripts/python.exe backend/scripts/save_live_data.py
```

Run this once per day (or any time you want fresh data).

### Start the API server

```
backend/venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Test it:
```
curl http://localhost:8000/health
```

Should return: `{"status":"ok"}`

---

## 5. Frontend Setup

### Install packages

```
cd frontend
npm install
```

### Environment variable

The frontend reads one variable from `frontend/.env.local`. It should already exist with:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

If the file is missing, create it with that content.

### Start the dev server

```
cd frontend
npm run dev
```

Open http://localhost:3000 in a browser.

---

## 6. Full Data Flow (How It All Fits Together)

```
MLB Stats API  ──┐
                 ├──► save_live_data.py ──► PostgreSQL
OddsAPI.io    ──┘

PostgreSQL ──► FastAPI (port 8000) ──► GET /research/today ──► Next.js (port 3000)
```

The dashboard fetches `GET /research/today`, which returns today's games with
odds, pitchers, records, and line movement in one consolidated response.

---

## 7. Checking Things Are Working

| Check | Command |
|---|---|
| Database connected | `backend/venv/Scripts/python.exe backend/scripts/test_db_connection.py` |
| MLB data fetches | `backend/venv/Scripts/python.exe backend/test_mlb_stats_api.py` |
| Odds data fetches | `backend/venv/Scripts/python.exe backend/test_odds_fetcher.py` |
| Backend health | `curl http://localhost:8000/health` |
| Research endpoint | `curl http://localhost:8000/research/today` |
| Dashboard | Open http://localhost:3000 |

---

## 8. Active vs Paused Data Sources

| Source | Status | What It Provides |
|---|---|---|
| MLB Stats API | **Active** — free, no key | Games, probable pitchers, team records |
| OddsAPI.io | **Active** — requires `ODDS_API_KEY` | Bet365 + DraftKings moneylines |
| SportsDataIO | **Paused** — requires paid key | Nothing currently; kept as future fallback |

The SportsDataIO fetcher (`backend/fetchers/sportsdataio.py`) is ready to use if
needed later, but it is not called by any active code.
