-- =============================================================
-- MLB Betting Edge — Database Schema (Version 1 MVP)
-- PostgreSQL
-- =============================================================
-- Run this file once to create all tables.
-- Order matters: teams must exist before games,
-- games must exist before starting_pitchers and odds_history.
-- =============================================================


-- -------------------------------------------------------------
-- TABLE 1: teams
-- One row per MLB team. 30 rows total. Rarely changes.
-- -------------------------------------------------------------
CREATE TABLE teams (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100)    NOT NULL,   -- e.g. "New York Yankees"
    abbreviation    VARCHAR(5)      NOT NULL,   -- e.g. "NYY"
    city            VARCHAR(100)    NOT NULL,   -- e.g. "New York"

    UNIQUE (abbreviation)
);


-- -------------------------------------------------------------
-- TABLE 2: games
-- One row per MLB game. Home team hosts the game.
-- external_game_id is the MLB Stats API gamePk, used to match
-- API updates to the right row without creating duplicates.
-- -------------------------------------------------------------
CREATE TABLE games (
    id                  SERIAL PRIMARY KEY,
    external_game_id    VARCHAR(50)     NOT NULL,   -- MLB Stats API gamePk
    game_date           DATE            NOT NULL,
    game_time           VARCHAR(20),                -- e.g. "7:05 PM ET"
    home_team_id        INTEGER         NOT NULL REFERENCES teams(id),
    away_team_id        INTEGER         NOT NULL REFERENCES teams(id),
    status              VARCHAR(20)     NOT NULL DEFAULT 'scheduled',
        -- allowed values: 'scheduled', 'in_progress', 'final', 'postponed'
    home_score          INTEGER,                    -- null until game is final
    away_score          INTEGER,                    -- null until game is final

    UNIQUE (external_game_id)
);


-- -------------------------------------------------------------
-- TABLE 3: starting_pitchers
-- One row per game. Stores the starting pitcher names.
-- Pitcher names come from the MLB Stats API (probablePitcher).
-- -------------------------------------------------------------
CREATE TABLE starting_pitchers (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER     NOT NULL REFERENCES games(id),
    home_pitcher    VARCHAR(100),   -- null if not announced yet
    away_pitcher    VARCHAR(100),   -- null if not announced yet

    UNIQUE (game_id)    -- only one pitcher row per game
);


-- -------------------------------------------------------------
-- TABLE 4: odds_history
-- One row every time we record odds for a game.
-- Multiple rows per game = line movement over time.
-- Moneylines are stored as integers (e.g. -140, +120).
-- This is the most important table for tracking line movement.
-- -------------------------------------------------------------
CREATE TABLE odds_history (
    id              SERIAL PRIMARY KEY,
    game_id         INTEGER         NOT NULL REFERENCES games(id),
    sportsbook      VARCHAR(50)     NOT NULL DEFAULT 'unknown',  -- e.g. "Bet365"
    home_moneyline  INTEGER         NOT NULL,   -- e.g. -140 (favorite)
    away_moneyline  INTEGER         NOT NULL,   -- e.g. +120 (underdog)
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        -- TIMESTAMPTZ stores the exact time with timezone
);

-- This index makes it fast to look up all odds snapshots for a game,
-- sorted by time (newest first).
CREATE INDEX idx_odds_history_game_time
    ON odds_history (game_id, recorded_at DESC);


-- -------------------------------------------------------------
-- TABLE 5: team_records
-- One row per team per season. Updated daily.
-- Tracks overall, home, and away win/loss records.
-- -------------------------------------------------------------
CREATE TABLE team_records (
    id              SERIAL PRIMARY KEY,
    team_id         INTEGER     NOT NULL REFERENCES teams(id),
    season          INTEGER     NOT NULL,   -- e.g. 2026
    wins            INTEGER     NOT NULL DEFAULT 0,
    losses          INTEGER     NOT NULL DEFAULT 0,
    home_wins       INTEGER     NOT NULL DEFAULT 0,
    home_losses     INTEGER     NOT NULL DEFAULT 0,
    away_wins       INTEGER     NOT NULL DEFAULT 0,
    away_losses     INTEGER     NOT NULL DEFAULT 0,

    UNIQUE (team_id, season)    -- one record per team per season
);
