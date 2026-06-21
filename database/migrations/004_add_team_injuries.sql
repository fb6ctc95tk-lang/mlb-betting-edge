-- Migration 004 — add team_injuries table
-- Run once against the live database.
--
--   psql $DATABASE_URL -f database/migrations/004_add_team_injuries.sql
--
-- This table is cleared and repopulated on every ingestion run.
-- It holds current injury status only — no history is kept.

CREATE TABLE IF NOT EXISTS team_injuries (
    id                  SERIAL PRIMARY KEY,
    team_id             INTEGER     NOT NULL REFERENCES teams(id),
    player_name         VARCHAR(100) NOT NULL,
    injury_status       VARCHAR(50),
    injury_description  TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_team_injuries_team
    ON team_injuries (team_id);
