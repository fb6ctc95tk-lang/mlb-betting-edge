-- Migration 005 — add Oracle Phase 1 tables
-- Run once against the live database.
--
--   psql $DATABASE_URL -f database/migrations/005_add_oracle_phase1_tables.sql
--
-- Creates five Oracle Phase 1 tables in dependency order:
--   1. oracle_slate_runs         (parent of all Oracle tables)
--   2. oracle_game_analyses      (references oracle_slate_runs)
--   3. oracle_plays              (references oracle_slate_runs, oracle_game_analyses)
--   4. oracle_play_events        (references oracle_slate_runs, oracle_game_analyses, oracle_plays)
--   5. oracle_immutability_audit (no Oracle foreign keys)
--
-- The append-only trigger on oracle_play_events is added in a separate
-- authorized migration (WP-2). This file creates table structure only.
--
-- Identifiers are application-generated VARCHAR values:
--   oracle_slate_runs.slate_run_id  format: ORACLE-YYYYMMDD-NNN
--   oracle_game_analyses.game_run_id format: {slate_run_id}-{game_identifier}
--   oracle_plays.play_id             format: EO-YYYY-NNN
--
-- oracle_play_events.event_id and oracle_immutability_audit.audit_id
-- are database-generated BIGSERIAL values.


-- -------------------------------------------------------------
-- TABLE 1: oracle_slate_runs
-- One record per daily Oracle run. Carries the Slate Run ID,
-- the slate-level state machine status, and the daily play count.
-- The three-play maximum is enforced at the database level via
-- the chk_daily_plays_activated CHECK constraint.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_slate_runs (
    slate_run_id          VARCHAR         PRIMARY KEY,
    run_date              DATE            NOT NULL,
    run_status            VARCHAR,
    daily_plays_activated INTEGER         NOT NULL DEFAULT 0,
    run_started_at        TIMESTAMPTZ     NOT NULL,
    run_completed_at      TIMESTAMPTZ,
    created_at            TIMESTAMPTZ     DEFAULT NOW(),

    CONSTRAINT chk_daily_plays_activated
        CHECK (daily_plays_activated >= 0 AND daily_plays_activated <= 3)
);


-- -------------------------------------------------------------
-- TABLE 2: oracle_game_analyses
-- One record per game per daily slate run. Carries the Game
-- Analysis Run ID, the canonical MLB Stats API gamePk as
-- external_game_id, and the game-level state machine status.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_game_analyses (
    game_run_id       VARCHAR         PRIMARY KEY,
    slate_run_id      VARCHAR         NOT NULL
        REFERENCES oracle_slate_runs(slate_run_id),
    external_game_id  VARCHAR         NOT NULL,
    home_team         VARCHAR         NOT NULL,
    away_team         VARCHAR         NOT NULL,
    first_pitch_time  TIMESTAMPTZ     NOT NULL,
    game_status       VARCHAR,
    venue             VARCHAR,
    created_at        TIMESTAMPTZ     DEFAULT NOW()
);


-- -------------------------------------------------------------
-- TABLE 3: oracle_plays
-- One record per governed paper bet. Play ID is assigned only
-- at formal Oracle nomination via the governed nomination path.
-- pregame_locked_at non-null signals pregame fields are read-only
-- at the application layer.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_plays (
    play_id               VARCHAR         PRIMARY KEY,
    candidate_id          VARCHAR         NOT NULL,
    slate_run_id          VARCHAR         NOT NULL
        REFERENCES oracle_slate_runs(slate_run_id),
    game_run_id           VARCHAR         NOT NULL
        REFERENCES oracle_game_analyses(game_run_id),
    market                VARCHAR         NOT NULL,
    selected_side         VARCHAR         NOT NULL,
    odds_at_nomination    INTEGER         NOT NULL,
    stake_units           NUMERIC         DEFAULT 1.0,
    nomination_timestamp  TIMESTAMPTZ     NOT NULL,
    pregame_locked_at     TIMESTAMPTZ,
    play_status           VARCHAR,
    settlement_result     VARCHAR,
    mock_pnl              NUMERIC,
    closing_odds          INTEGER,
    clv                   NUMERIC,
    settled_at            TIMESTAMPTZ,
    created_at            TIMESTAMPTZ     DEFAULT NOW()
);


-- -------------------------------------------------------------
-- TABLE 4: oracle_play_events
-- Append-only event log. One record per Oracle event across all
-- 27 defined event types. event_id is database-generated (BIGSERIAL).
-- The database-level append-only trigger is added in WP-2.
-- game_run_id and play_id are nullable: slate-level events have
-- no game or play context.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_play_events (
    event_id          BIGSERIAL       PRIMARY KEY,
    event_type        VARCHAR         NOT NULL,
    slate_run_id      VARCHAR         NOT NULL
        REFERENCES oracle_slate_runs(slate_run_id),
    game_run_id       VARCHAR
        REFERENCES oracle_game_analyses(game_run_id),
    play_id           VARCHAR
        REFERENCES oracle_plays(play_id),
    event_timestamp   TIMESTAMPTZ     NOT NULL,
    event_payload     JSONB,
    recorded_at       TIMESTAMPTZ     DEFAULT NOW()
);


-- -------------------------------------------------------------
-- TABLE 5: oracle_immutability_audit
-- Records every rejected write attempt on oracle_play_events.
-- Populated exclusively by the PostgreSQL trigger added in WP-2.
-- audit_id is database-generated (BIGSERIAL).
-- No foreign keys to other Oracle tables.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_immutability_audit (
    audit_id          BIGSERIAL       PRIMARY KEY,
    rejected_event_id BIGINT,
    violation_type    VARCHAR         NOT NULL,
    rejected_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    attempted_by      VARCHAR         NOT NULL,
    detail            TEXT
);
