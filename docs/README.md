# Docs

This folder contains reference material, research notes, and API documentation.

## What Lives Here

- **API notes** — data provider endpoint reference and examples
- **Betting research** — notes on betting strategies and models
- **Architecture decisions** — why we made certain tech choices

## Folder Structure (will grow over time)

```
docs/
├── api/
│   ├── mlb_stats_api.md      # Free MLB Stats API endpoints we use
│   ├── sportsdataio.md       # SportsDataIO endpoints (paused)
│   └── responses/            # Example JSON responses from the API
├── betting/
│   ├── moneyline_notes.md    # Research on moneyline betting
│   ├── props_notes.md        # Research on player props
│   └── bvp_analysis.md      # Batter vs Pitcher strategy notes
└── architecture.md           # Overall system design decisions
```

## MLB Stats API (Active — Free, No Key)

Base URL: `https://statsapi.mlb.com/api/v1`

Endpoints we use:
- `/schedule?sportId=1&date={date}&hydrate=probablePitcher,team` — today's games + starting pitchers
- `/standings?leagueId=103,104&season={year}&hydrate=team` — team win/loss records
  (103 = American League, 104 = National League)

These power `backend/fetchers/mlb_stats_api.py`. No signup or API key required.

## SportsDataIO API (Paused)

Base URL: `https://api.sportsdata.io/v3/mlb`

Endpoints we may use later (once we add odds data):
- `/scores/json/GamesByDate/{date}` — today's games
- `/stats/json/PlayerSeasonStats/{season}` — season stats
- `/odds/json/GameOddsByDate/{date}` — moneylines and totals
- `/stats/json/BatterVsPitcherStats` — batter vs pitcher history

Code lives in `backend/fetchers/sportsdataio.py`, ready but not active.

## Odds Data (Not Yet Decided)

Free official MLB data does not include betting odds. We need to pick a
source for moneylines and line movement before Step 3. Options to evaluate:
- The Odds API (free tier, separate signup required)
- Reactivating SportsDataIO's odds endpoint (paid)
