# Database

This folder contains the PostgreSQL database schema for MLB Betting Edge.

## How to Create the Database (when ready)

You only need to run one file:

```sql
-- In your PostgreSQL client or terminal:
\i schema.sql
```

That creates all 5 tables at once.

---

## The 5 Tables

### Table 1: `teams`

Stores all 30 MLB teams. This is the simplest table and acts as a lookup.

| Column       | Type    | Example              |
|--------------|---------|----------------------|
| id           | number  | 1                    |
| name         | text    | New York Yankees     |
| abbreviation | text    | NYY                  |
| city         | text    | New York             |

**Plain English:** A phonebook of every MLB team. Every other table refers back
to this one by team id number instead of repeating the full team name everywhere.

---

### Table 2: `games`

One row per MLB game. Stores the schedule and final scores.

| Column           | Type    | Example              |
|------------------|---------|----------------------|
| id               | number  | 101                  |
| external_game_id | text    | 60255 (MLB Stats API gamePk) |
| game_date        | date    | 2026-06-08           |
| game_time        | text    | 7:05 PM ET           |
| home_team_id     | number  | 1 (→ teams table)    |
| away_team_id     | number  | 5 (→ teams table)    |
| status           | text    | scheduled            |
| home_score       | number  | null (not played yet)|
| away_score       | number  | null (not played yet)|

**Plain English:** A calendar page for every game. `home_team_id` and
`away_team_id` are not team names — they are ID numbers that point to
the `teams` table. `external_game_id` is the MLB Stats API's `gamePk`
for that game, so we can match daily API updates to the right row
without creating duplicates.

**Status values:**
- `scheduled` — game hasn't started
- `in_progress` — game is live
- `final` — game is over, scores are filled in
- `postponed` — game was cancelled or delayed

---

### Table 3: `starting_pitchers`

One row per game. Stores who is pitching for each side.

| Column       | Type   | Example          |
|--------------|--------|------------------|
| id           | number | 1                |
| game_id      | number | 101 (→ games)    |
| home_pitcher | text   | Gerrit Cole      |
| away_pitcher | text   | Chris Sale       |

**Plain English:** A sticky note attached to each game card that says
"these two guys are pitching." Pitcher names can be null early in the
day if the team hasn't announced yet.

---

### Table 4: `odds_history`

Multiple rows per game. Every time we check the betting lines, we save
a new row with a timestamp. This is how we track line movement.

| Column        | Type      | Example                    |
|---------------|-----------|----------------------------|
| id            | number    | 1                          |
| game_id       | number    | 101 (→ games)              |
| home_moneyline| integer   | -140                       |
| away_moneyline| integer   | +120                       |
| recorded_at   | timestamp | 2026-06-08 09:00:00-05:00  |

**Plain English:** A logbook that records the odds for every game every
time we check. If we check 6 times a day, we get 6 rows per game. Put
those rows in order by time and you can see exactly how the line moved.

**Reading moneylines:**
- `-140` means you must bet $140 to win $100 (this team is the favorite)
- `+120` means you bet $100 to win $120 (this team is the underdog)
- When a line moves from -130 to -150, sharp money is coming in on that team

**Why this is the most important table:** See section below.

---

### Table 5: `team_records`

One row per team per season. Updated once a day.

| Column      | Type   | Example |
|-------------|--------|---------|
| id          | number | 1       |
| team_id     | number | 1 (→ teams) |
| season      | number | 2026    |
| wins        | number | 42      |
| losses      | number | 28      |
| home_wins   | number | 24      |
| home_losses | number | 11      |
| away_wins   | number | 18      |
| away_losses | number | 17      |

**Plain English:** The current standings for every team. Home vs away
records matter because some teams are much stronger at home than on the road.

---

## How the Tables Connect

```
                        teams
                       /     \
           home_team_id       away_team_id
                     \         /
                       games
                      /     \
        starting_pitchers   odds_history
```

- `teams` is the foundation — everything else refers to it
- `games` is the center — starting_pitchers and odds_history both attach to a game
- `team_records` connects back to `teams` (one record per team per season)

In database terms, when one table points to another using an ID number,
that connection is called a **foreign key**. It prevents orphaned data
(e.g., you can't save odds for a game that doesn't exist).

---

## Why `odds_history` Is the Most Important Table for Line Movement

Every other table stores one fact per row (one team, one game, one pitcher).

`odds_history` is different. It is a **time series** — it stores the
same game's odds again and again, each time stamped with when we recorded it.

Example: Yankees vs Red Sox on June 8, 2026

| Time       | NYY moneyline | BOS moneyline | What it means            |
|------------|---------------|---------------|--------------------------|
| 9:00 AM    | -130          | +110          | Yankees slight favorite  |
| 12:00 PM   | -145          | +125          | Money coming in on NYY   |
| 4:00 PM    | -155          | +135          | Even more NYY money      |
| 6:30 PM    | -150          | +130          | Slight pullback           |

Reading this table, you can see:
1. The line opened at -130 (Yankees moderately favored)
2. It moved to -155 by afternoon (sharp money bet the Yankees heavily)
3. It pulled back slightly — sportsbooks adjusted to balance action

**Line movement is one of the most useful signals in sports betting.**
When a line moves against the public (most bettors on one side, but
the line moves the other way), it often means professional bettors
("sharps") are on the other side. `odds_history` is what makes that
analysis possible.

---

## Files in This Folder

| File        | Purpose                              |
|-------------|--------------------------------------|
| schema.sql  | Creates all 5 tables — run this once |
| README.md   | This file                            |
