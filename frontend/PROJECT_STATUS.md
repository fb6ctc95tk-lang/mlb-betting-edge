# Project Status

## Project
MLB Betting Edge — personal sports betting research dashboard.

## Tech Stack
- Frontend: Next.js 16 (App Router, React 19, TypeScript)
- Backend: Python + FastAPI
- Database: PostgreSQL
- Data: SportsDataIO API

---

## Completed Features

### Research Discovery
- Today's games table with full game data
- Date picker with available-dates API integration
- Filter: Has Injuries
- Filter: Has Significant Line Movement
- Filter: Has Weather Context
- Sort: Largest Line Movement
- Multi-filter support (all filters combinable)
- Research Flags display per game row (injury / line movement / weather)
- Flag summary counts in toolbar

### Research Workspace
- Add games to workspace shortlist
- Remove games from workspace
- Workspace persists between sessions (localStorage)
- Workspace game count displayed in toolbar
- Workspace Notes v1:
  - Plain text notes per workspace game
  - Auto-save on every keystroke
  - 1000 character limit
  - Persists between sessions (localStorage)

### Comparison View
- Side-by-side comparison table for two selected games
- Auto-select comparison when workspace contains exactly 2 games
- Manual game selection via dropdowns (workspace games only)
- **Sections:**
  - Research Flags
  - Matchup (teams, date, time, status)
  - Pitchers (away + home starters)
  - Recent Form (last 10 record + run differential)
  - Team Streaks
  - Team Splits (road/home records)
  - Weather
  - Bullpen (last game innings pitched)
  - Injuries (away + home)
  - Odds (Bet365 + DraftKings moneylines)
  - Line Movement (max move, direction)

### Game Detail Page
- Individual game page at `/game/[game_id]`

### Dashboard Infrastructure
- Data Quality card
- Ingestion Status card
- Reusable `ResearchFlags` component
- Reusable `getGameFlags()` logic
- Reusable `getGameFlagSummary()` logic
- Reusable `applyFilters()` logic

---

## Test Suite
- 3 test files, 34 tests — all passing
- `lib/gameFilters.test.ts` — filter logic (12 tests)
- `lib/gameFlags.test.ts` — flag detection (12 tests)
- `lib/gameFlagSummary.test.ts` — flag summary counts (10 tests)

---

## Sprint History

| Sprint | Delivered | Commit |
|---|---|---|
| Research Flags | Flag detection, display, summary | `7b861b5` |
| Research Workspace | Add/remove/persist workspace games | `b2d984b` |
| Comparison View v1 | Side-by-side comparison table | `383e139` |
| Multi-Filter Discovery | Filter + sort combinations | `451932a` |
| Reusable Flags | Extracted shared flag component | `2255d98` |
| Flag Summary Display | Toolbar flag counts | `dcbee17` |
| Research Workflow Visibility | Dashboard workflow improvements | `e47cd3a` |
| Comparison View v2 | Auto-select, form/streak/splits, sections | `ea10af1` |
| Lint Compliance | ESLint set-state-in-effect fixes | `e79ecd6` |
| Workspace Notes v1 | Per-game notes with auto-save | `75c4c9a` |

---

## Validation (latest)
| Check | Result |
|---|---|
| ESLint | PASS — 0 errors |
| TypeScript | PASS — 0 errors |
| Tests | PASS — 34/34 |

---

## Current Workflow
```
Discover Games → Apply Filters → Review Flags → Add To Workspace
      → Workspace Notes → Game Detail Research → Compare Games
```

## Current Phase
Research Experience Expansion

## Next Focus
Evaluate the next workflow bottleneck before beginning another sprint.
