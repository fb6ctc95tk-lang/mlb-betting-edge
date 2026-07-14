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
- Team win/loss records, last-10 form, streaks, and road/home splits
- Bet365 and DraftKings moneyline odds
- Implied probabilities (calculated from moneylines)
- Line movement — opening vs latest odds, movement delta, per sportsbook per side
- Weather context per game — temperature, wind, precipitation
- Injury reports per team
- Bullpen load context (innings from previous game)
- Research Insights — pattern detection per game (form vs. market divergence, record vs. recent form divergence)
- Market Opportunity layer — research candidates for FULL_GAME_MONEYLINE, surfaced from Research Insights
- Market Research Board (`/opportunities`) — all Market Opportunities for a date, with historical date selector
- Game Detail page — full research breakdown per game including Research Insights panel
- Research Workspace — pin games and add notes, persisted in localStorage
- Comparison View — side-by-side table for two workspace games
- Historical date selector — view any stored date on the homepage and the board
- Research filters and sort — injuries, line movement, weather context; default or line-move sort
- Automated daily ingestion — Windows Task Scheduler at 11 AM and 7 PM

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| GET | `/health/ingestion` | Last ingestion run time and exit code |
| GET | `/health/data-quality` | Data completeness check |
| GET | `/research/today` | Full research payload for today's games |
| GET | `/research/date/{date}` | Full research payload for any stored historical date |
| GET | `/research/available-dates` | All stored game dates, newest first |
| GET | `/research/game/{game_id}` | Full research detail for a single game |
| GET | `/games/today` | Raw game list (no research data) |
| GET | `/odds/movement` | Line movement with optional filters |
| GET | `/teams` | All 30 teams |

The homepage and Market Research Board use `/research/today` and `/research/date/{date}`. The Game Detail page uses `/research/game/{game_id}`.

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
