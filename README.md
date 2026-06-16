# MLB Betting Edge

A personal MLB betting research dashboard. Pulls live game data, moneyline odds, and line movement into one readable view.

## What This Does

- Pulls today's MLB games, probable pitchers, and team records from the free MLB Stats API
- Pulls moneyline odds from OddsAPI.io (Bet365 + DraftKings via free tier)
- Stores everything in a local PostgreSQL database
- Serves it through a Python FastAPI backend
- Displays it in a Next.js dashboard

## Current Features

- Today's MLB games with game time and status
- Probable starting pitchers for each game
- Team win/loss records
- Bet365 and DraftKings moneyline odds
- Implied probabilities (calculated from moneylines)
- Line movement — opening vs latest odds, movement delta, per sportsbook per side

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| GET | `/games/today` | Today's games (no odds) |
| GET | `/games/today-with-odds` | Today's games with latest moneylines and team records |
| GET | `/odds/latest` | Latest moneyline per game and sportsbook |
| GET | `/odds/today` | Latest moneylines for today's games |
| GET | `/odds/movement` | Opening vs latest moneyline per game/sportsbook/side |
| GET | `/odds/movement/summary` | Same but only rows where movement ≠ 0, sorted by \|movement\| desc |
| GET | `/research/today` | Consolidated view: games + records + pitchers + odds + line movement |
| GET | `/teams` | All teams |

The dashboard uses `GET /research/today` as its primary data source.

## Tech Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Database  | PostgreSQL                          |
| Backend   | Python + FastAPI                    |
| Frontend  | Next.js (React)                     |
| Game data | MLB Stats API (free, no key needed) |
| Odds data | OddsAPI.io (free tier, 2 sportsbooks) |
| Hosting   | Supabase + Railway + Vercel (future) |

## Getting Started

See `PROJECT_PLAN.md` for the build roadmap and progress.
See each folder's `README.md` for setup instructions.

## Folder Structure

```
mlb-betting-edge/
├── backend/         # Python FastAPI server + data ingestion scripts
├── frontend/        # Next.js web dashboard
├── database/        # SQL schema
├── docs/            # Notes, API references, research
├── README.md
├── PROJECT_PLAN.md  # Build roadmap with progress tracking
├── MVP_PLAN.md      # Original MVP scope and definition of done
└── CLAUDE.md        # Instructions for Claude Code
```
