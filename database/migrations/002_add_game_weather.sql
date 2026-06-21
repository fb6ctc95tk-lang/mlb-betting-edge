-- Migration 002 — add game_weather table
-- Run once against the live database.
--
--   psql $DATABASE_URL -f database/migrations/002_add_game_weather.sql

CREATE TABLE IF NOT EXISTS game_weather (
    id                      SERIAL PRIMARY KEY,
    game_id                 INTEGER         NOT NULL REFERENCES games(id),
    temperature             NUMERIC(5, 1),      -- °F
    wind_speed              NUMERIC(5, 1),      -- mph
    wind_direction          INTEGER,            -- degrees (0–360)
    precipitation_chance    INTEGER,            -- % (0–100)
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (game_id)
);
