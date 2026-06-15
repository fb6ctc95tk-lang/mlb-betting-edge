# MLB Betting Edge

A personal MLB betting research dashboard for smarter, data-driven wagers.

## What This Does

- Pulls live and historical MLB data from the SportsDataIO API
- Stores it in a PostgreSQL database
- Serves it through a Python FastAPI backend
- Displays it in a Next.js web dashboard

## Features (Planned)

- Moneyline betting analysis
- Player props tracking
- Team matchup analysis
- Batter vs Pitcher breakdowns
- Line movement tracking
- Parlay builder

## Tech Stack

| Layer     | Technology         |
|-----------|--------------------|
| Database  | PostgreSQL         |
| Backend   | Python + FastAPI   |
| Frontend  | Next.js (React)    |
| Data API  | SportsDataIO       |
| Hosting   | Supabase + Railway + Vercel (later) |

## Getting Started

See `PROJECT_PLAN.md` for the build roadmap.
See each folder's `README.md` for setup instructions.

## Folder Structure

```
mlb-betting-edge/
├── backend/      # Python FastAPI server + data fetching
├── frontend/     # Next.js web dashboard
├── database/     # SQL schema and migration files
├── docs/         # Notes, API references, research
├── README.md
├── PROJECT_PLAN.md
└── CLAUDE.md
```
