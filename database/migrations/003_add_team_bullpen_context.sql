-- Migration 003 — add team_bullpen_context table
-- Run once against the live database.
--
--   psql $DATABASE_URL -f database/migrations/003_add_team_bullpen_context.sql

CREATE TABLE IF NOT EXISTS team_bullpen_context (
    id                          SERIAL PRIMARY KEY,
    team_id                     INTEGER     NOT NULL REFERENCES teams(id),
    reference_date              DATE        NOT NULL,   -- the game date this context was computed for
    previous_game_date          DATE,
    bullpen_innings_last_game   NUMERIC(5, 1),          -- baseball IP notation: 3.1 = 3 innings + 1 out
    played_yesterday            BOOLEAN,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (team_id, reference_date)
);
