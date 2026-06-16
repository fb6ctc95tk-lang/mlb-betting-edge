# App Architecture

## Overview

MLB Betting Edge is a read-only research dashboard. Data flows in one direction:
external APIs → PostgreSQL → FastAPI → Next.js.

There are no write endpoints. The dashboard does not calculate edges, picks, parlays, props, predictions, or model scores.

---

## Data Flow

```
┌─────────────────┐     ┌─────────────────────────┐     ┌────────────┐
│  MLB Stats API  │────►│                         │     │            │
│  (free, no key) │     │  save_live_data.py      │────►│ PostgreSQL │
│                 │     │  (run once per day)      │     │            │
│  OddsAPI.io     │────►│                         │     │            │
│  (free tier)    │     └─────────────────────────┘     └─────┬──────┘
└─────────────────┘                                           │
                                                              │
                                                    ┌─────────▼──────────┐
                                                    │     FastAPI        │
                                                    │                    │
                                                    │  /games/today      │
                                                    │  /odds/today       │
                                                    │  /odds/movement    │
                                                    │  /odds/movement/   │
                                                    │    summary         │
                                                    │  /research/today ◄─┼── primary
                                                    │  /teams            │
                                                    └─────────┬──────────┘
                                                              │
                                                    ┌─────────▼──────────┐
                                                    │  Next.js Dashboard │
                                                    │                    │
                                                    │  Fetches:          │
                                                    │  GET /research/    │
                                                    │      today         │
                                                    └────────────────────┘
```

---

## Layers

### Ingestion Layer

`backend/scripts/save_live_data.py` — runs once per day (manually or scheduled).

Fetches from:
- **MLB Stats API** — games, probable pitchers, standings
- **OddsAPI.io** — Bet365 + DraftKings moneyline odds

Saves to PostgreSQL using UPSERT (safe to re-run, no duplicates).

### Database

PostgreSQL running locally (`mlb_betting_edge` database).

| Table | Contents |
|-------|----------|
| `teams` | All 30 MLB teams (static) |
| `games` | Daily schedule with scores and status |
| `starting_pitchers` | One row per game — home and away probable pitchers |
| `odds_history` | Timestamped moneyline snapshots (enables line movement) |
| `team_records` | Win/loss records per team per season |

### Backend

Python + FastAPI, running on port 8000. One psycopg2 connection opened and closed per request. Read-only — no POST/PUT/DELETE endpoints.

### Research Layer

`GET /research/today` is the aggregation endpoint. It runs four queries in one connection and returns a single list of game objects, each containing:

- game metadata (date, time, status)
- team abbreviations, records, probable pitchers
- `odds` — latest moneyline per sportsbook with implied probabilities
- `line_movement` — opening vs latest per sportsbook per side

This is the endpoint the dashboard uses. Individual endpoints (`/games/today`, `/odds/movement`, etc.) remain available for direct use.

### Frontend

Next.js (TypeScript, App Router) on port 3000. Single `page.tsx` fetches `GET /research/today` on mount and renders two tables:

1. **Today's MLB Games** — one row per game with teams, time, status, pitchers, records, Bet365 odds, DraftKings odds, implied probabilities
2. **Line Movement** — one row per game × sportsbook × side, showing opening moneyline, latest moneyline, and delta (color-coded: green=positive, crimson=negative, gray=zero)

---

## What This Is Not

- No betting recommendations
- No edge calculations or confidence scores
- No machine learning or probability models
- No parlays, props, or predictions
- No user authentication
- No write operations of any kind
