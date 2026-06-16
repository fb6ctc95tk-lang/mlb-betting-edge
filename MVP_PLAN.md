# MLB Betting Edge — MVP Plan (Version 1)

## The Golden Rule of Version 1

> Build the smallest thing that is actually useful.

Version 1 is NOT the finished app. It is the foundation that proves the system works
end-to-end: data comes in, gets stored, and gets displayed. Everything else comes later.

---

## 1. What Version 1 Does

Version 1 is a **daily game viewer with moneyline odds and line movement**.

When you open the dashboard, you see:

- Today's MLB games
- The starting pitcher for each team
- The current moneyline odds (which team is favored and by how much)
- How the moneyline has moved since it opened (line movement)
- Each team's current record (wins and losses)

That's it. No props. No parlays. No advanced stats.

> **Data source update (2026-06-10):** Games, starting pitchers, and team
> records now come from the **free MLB Stats API** (no key needed).
> SportsDataIO is paused but kept ready for later.

> **Odds source confirmed (2026-06-16):** Moneyline odds come from
> **OddsAPI.io** (free tier). The free tier locks the account to two
> sportsbooks: **Bet365** and **DraftKings**. Both are saved in
> `odds_history` with a `sportsbook` column and a timestamp, enabling
> line movement tracking.

If you can sit down each morning, look at the day's games, see who's pitching,
see the odds, and see if the line has moved — Version 1 is a success.

---

## 2. What Data We Absolutely Need

These are the things Version 1 cannot work without:

| Data | Why We Need It |
|---|---|
| **Teams** | Every game involves two teams — we need their names and abbreviations |
| **Games** | The schedule: who plays who, when, and where |
| **Starting Pitchers** | The single biggest factor in MLB moneyline betting |
| **Moneyline Odds** | The actual betting lines (e.g., Yankees -140, Red Sox +120) |
| **Odds Timestamps** | So we can see how the line moved over time |
| **Team Records** | Win/loss record gives quick context on team strength |

---

## 3. What We Can Ignore Until Version 2

Do not touch these in Version 1. They will complicate the build and slow us down.

| Ignored Feature | Why It Can Wait |
|---|---|
| Player props (strikeouts, hits, RBIs) | Needs a different data structure and UI |
| Batter vs Pitcher analysis | Complex, needs large historical dataset |
| Parlay builder | Needs props + multiple games logic |
| Bullpen / relief pitcher stats | Extra complexity, not core to moneyline |
| Weather data | Nice to have, not essential |
| Injuries | Hard to track reliably, save for V2 |
| Advanced betting models / AI / ML | Way too early — garbage in, garbage out |
| Run line / totals (over/under) | Moneyline first, then expand odds types |
| Historical game results / scores | Useful later for backtesting, not now |

---

## 4. The Simplest Database Schema Possible

Think of the database as a spreadsheet. Each "table" is one sheet.
Here are the 5 sheets Version 1 needs:

---

### Table 1: `teams`
Stores all 30 MLB teams. This never really changes.

```
teams
├── id              (a unique number for each team, e.g. 1, 2, 3...)
├── name            (full name, e.g. "New York Yankees")
├── abbreviation    (short code, e.g. "NYY")
└── city            (e.g. "New York")
```

Example row: `1 | New York Yankees | NYY | New York`

---

### Table 2: `games`
One row per game. Stores the schedule and final scores once games are played.

```
games
├── id              (unique number for each game)
├── game_date       (the date of the game, e.g. 2026-06-08)
├── home_team_id    (points to the teams table)
├── away_team_id    (points to the teams table)
├── game_time       (scheduled start time)
├── status          (scheduled / in_progress / final)
├── home_score      (filled in after the game)
└── away_score      (filled in after the game)
```

Example row: `101 | 2026-06-08 | 1 (Yankees) | 5 (Red Sox) | 7:05 PM | scheduled | null | null`

---

### Table 3: `starting_pitchers`
One row per game, listing who is pitching for each team.

```
starting_pitchers
├── id
├── game_id         (points to the games table)
├── home_pitcher    (name as a string, e.g. "Gerrit Cole")
└── away_pitcher    (name as a string, e.g. "Chris Sale")
```

Why not store pitcher stats here? Because Version 1 just needs the name.
Stats come in Version 2.

---

### Table 4: `odds`
One row every time we record the odds for a game. Multiple rows per game
is how we track line movement.

```
odds
├── id
├── game_id         (points to the games table)
├── home_moneyline  (e.g. -140 means bet $140 to win $100)
├── away_moneyline  (e.g. +120 means bet $100 to win $120)
└── recorded_at     (timestamp: when we captured this line)
```

Example rows for one game:
```
1 | game 101 | -130 | +110 | 2026-06-08 9:00 AM   ← opening line
2 | game 101 | -150 | +130 | 2026-06-08 2:00 PM   ← line moved!
3 | game 101 | -145 | +125 | 2026-06-08 6:00 PM   ← moved again
```

This is how we know if money is pouring in on one side.

---

### Table 5: `team_records`
Current win/loss record for each team, updated daily.

```
team_records
├── id
├── team_id         (points to the teams table)
├── season          (e.g. 2026)
├── wins
├── losses
├── home_wins
├── home_losses
├── away_wins
└── away_losses
```

One row per team per season. Simple.

---

### Visual: How the Tables Connect

```
teams ──────────────────────────────────────────┐
  │                                              │
  ├── (home_team_id) ──→ games ←── (away_team_id)
  │                        │
  └── team_records         ├──→ starting_pitchers
                           └──→ odds
```

`games` is the center of everything. Every other table points back to a game.

---

## 5. Recommended Development Order

Build in this exact order. Do not skip ahead. Each step depends on the one before it.

```
Step 1 — Database schema
   Write the SQL to create those 5 tables.
   Test that they work by inserting a fake game manually.
   ✓ Done when: tables exist in PostgreSQL, can insert and read data.

Step 2 — SportsDataIO connection
   Write a small Python script that calls the API and prints the response.
   No database yet. Just prove the API works.
   ✓ Done when: you can print today's games in the terminal.

Step 3 — Data fetcher scripts
   Write Python scripts that fetch games, odds, and pitchers
   from SportsDataIO and save them into the database.
   ✓ Done when: running the script puts real data in the database.

Step 4 — FastAPI backend
   Build the server with these 3 simple endpoints:
     GET /games/today        → list of today's games
     GET /games/{id}/odds    → odds history for one game
     GET /teams              → all team records
   ✓ Done when: you can call these URLs and get back JSON data.

Step 5 — Next.js frontend
   Build one simple page: a table of today's games with
   team names, pitchers, records, and current moneylines.
   ✓ Done when: you can open a browser and see today's games.

Step 6 — Line movement view
   Add a simple chart or table that shows how the odds
   changed throughout the day for any selected game.
   ✓ Done when: clicking a game shows its odds history.
```

---

## Version 1 Definition of Done

Version 1 is complete when you can do this:

1. ✅ Open the dashboard in a browser
2. ✅ See all of today's MLB games
3. ✅ See the starting pitcher for each game
4. ✅ See each team's win/loss record
5. ✅ See the current moneyline for each game
6. ✅ See how the line has moved (line movement table per sportsbook per side)

**Version 1 is complete as of 2026-06-16.** The dashboard shows all six items above using a single consolidated `GET /research/today` endpoint. Line movement is shown as a table (not a per-game chart — that is a Phase 4 enhancement).

That is the whole thing. Clean, useful, fast to build.

---

## What Version 2 Will Add (for reference — do not build yet)

- Player props (strikeouts, hits, total bases)
- Batter vs Pitcher historical stats
- Run line and totals (over/under)
- Team vs team recent form
- Parlay builder
- Injury reports

---

*Next step: Build Step 1 — the database schema (5 SQL files in the `database/schema/` folder).*
