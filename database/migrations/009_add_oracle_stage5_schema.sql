-- Migration 009: Oracle Inc-3 Stage 5 schema additions
-- Adds the five Stage 5 MVP tables and seeds the active MLB-A3-v1 sport policy.
-- Authorized by PM-1009 under PM-1007 / co-issued CWP-01/TAR Step 4 + PM-474 §7.
--
-- Tables (all immutable / append-only per PM-1007 §6):
--   1. oracle_stage5_results       — immutable aggregate four-engine result
--   2. oracle_preliminary_outputs  — immutable consumer-visible Preliminary output
--   3. oracle_scheduled_cutoffs    — immutable cutoff schedule (replay by game_run_id)
--   4. oracle_sport_policies       — append-only sport-policy versions
--   5. oracle_sport_policy_active  — append-only active-version designations (latest wins)
--
-- Rerunnable: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION / CREATE OR REPLACE TRIGGER (PG 14+), and
-- idempotent seed via WHERE NOT EXISTS. Never modifies migrations 001-008.
-- No destructive DROP or existing-column alteration.

-- ---------------------------------------------------------------------------
-- 1. oracle_stage5_results: one row per successful Stage 5 aggregate result
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oracle_stage5_results (
    stage5_result_id  TEXT         PRIMARY KEY,
    game_run_id       TEXT         NOT NULL,
    slate_run_id      TEXT         NOT NULL,
    ecf_result_id     TEXT         NOT NULL,
    data_version_id   TEXT         NOT NULL,
    verdict           TEXT         NOT NULL,
    engine_outputs    JSONB        NOT NULL,
    model_version     TEXT         NOT NULL,
    computed_at       TIMESTAMPTZ  NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_stage5_results_game_run_id
    ON oracle_stage5_results (game_run_id);

CREATE INDEX IF NOT EXISTS idx_oracle_stage5_results_slate_run_id
    ON oracle_stage5_results (slate_run_id);

CREATE OR REPLACE FUNCTION oracle_stage5_results_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_stage5_results is append-only: % on stage5_result_id % is not permitted',
        TG_OP, OLD.stage5_result_id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_stage5_results_append_only
    BEFORE UPDATE OR DELETE ON oracle_stage5_results
    FOR EACH ROW EXECUTE FUNCTION oracle_stage5_results_append_only();

-- ---------------------------------------------------------------------------
-- 2. oracle_preliminary_outputs: consumer-visible Preliminary output record.
-- Created at Stage 5 commit; carries Preliminary status at creation and is
-- never modified (Phase B §6.4). CHECK pins the status literal.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oracle_preliminary_outputs (
    id                BIGSERIAL    PRIMARY KEY,
    game_run_id       TEXT         NOT NULL,
    slate_run_id      TEXT         NOT NULL,
    stage5_result_id  TEXT         NOT NULL,
    consumer_status   TEXT         NOT NULL DEFAULT 'Preliminary'
        CHECK (consumer_status = 'Preliminary'),
    verdict           TEXT         NOT NULL,
    output_payload    JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_preliminary_outputs_game_run_id
    ON oracle_preliminary_outputs (game_run_id);

CREATE INDEX IF NOT EXISTS idx_oracle_preliminary_outputs_slate_run_id
    ON oracle_preliminary_outputs (slate_run_id);

CREATE OR REPLACE FUNCTION oracle_preliminary_outputs_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_preliminary_outputs is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_preliminary_outputs_append_only
    BEFORE UPDATE OR DELETE ON oracle_preliminary_outputs
    FOR EACH ROW EXECUTE FUNCTION oracle_preliminary_outputs_append_only();

-- ---------------------------------------------------------------------------
-- 3. oracle_scheduled_cutoffs: durable cutoff schedule. Natural key is
-- game_run_id (one active cutoff per game); replay semantics enforced in the
-- Orchestrator (read-before-insert). Persist-only; firing is deferred.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oracle_scheduled_cutoffs (
    id                   BIGSERIAL    PRIMARY KEY,
    game_run_id          TEXT         NOT NULL UNIQUE,
    slate_run_id         TEXT         NOT NULL,
    scheduled_cutoff_at  TIMESTAMPTZ  NOT NULL,
    policy_version_id    TEXT         NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_scheduled_cutoffs_slate_run_id
    ON oracle_scheduled_cutoffs (slate_run_id);

CREATE INDEX IF NOT EXISTS idx_oracle_scheduled_cutoffs_scheduled_cutoff_at
    ON oracle_scheduled_cutoffs (scheduled_cutoff_at);

CREATE OR REPLACE FUNCTION oracle_scheduled_cutoffs_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_scheduled_cutoffs is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_scheduled_cutoffs_append_only
    BEFORE UPDATE OR DELETE ON oracle_scheduled_cutoffs
    FOR EACH ROW EXECUTE FUNCTION oracle_scheduled_cutoffs_append_only();

-- ---------------------------------------------------------------------------
-- 4. oracle_sport_policies: append-only sport-policy versions. time_cutoff_offset
-- is stored in whole seconds (negative offsets precede first pitch).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oracle_sport_policies (
    id                          BIGSERIAL    PRIMARY KEY,
    sport_id                    TEXT         NOT NULL,
    policy_version_id           TEXT         NOT NULL UNIQUE,
    time_cutoff_offset_seconds  INTEGER      NOT NULL,
    finalization_event_types    JSONB        NOT NULL,
    qualifying_change_criteria  JSONB        NOT NULL,
    governance_reference        TEXT         NOT NULL,
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_sport_policies_sport_id
    ON oracle_sport_policies (sport_id);

CREATE OR REPLACE FUNCTION oracle_sport_policies_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_sport_policies is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_sport_policies_append_only
    BEFORE UPDATE OR DELETE ON oracle_sport_policies
    FOR EACH ROW EXECUTE FUNCTION oracle_sport_policies_append_only();

-- ---------------------------------------------------------------------------
-- 5. oracle_sport_policy_active: append-only active-version designations.
-- The active version for a sport is the most recent row (highest id). Future
-- PM governance re-designations append a new row; they do not mutate history.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oracle_sport_policy_active (
    id                    BIGSERIAL    PRIMARY KEY,
    sport_id              TEXT         NOT NULL,
    policy_version_id     TEXT         NOT NULL,
    governance_reference  TEXT         NOT NULL,
    designated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_sport_policy_active_sport_id
    ON oracle_sport_policy_active (sport_id);

CREATE OR REPLACE FUNCTION oracle_sport_policy_active_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_sport_policy_active is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_sport_policy_active_append_only
    BEFORE UPDATE OR DELETE ON oracle_sport_policy_active
    FOR EACH ROW EXECUTE FUNCTION oracle_sport_policy_active_append_only();

-- ---------------------------------------------------------------------------
-- Seed MLB-A3-v1 and its initial active designation atomically & idempotently.
-- Cutoff is 15 minutes before scheduled first pitch: offset = -900 seconds.
-- ---------------------------------------------------------------------------

INSERT INTO oracle_sport_policies
    (sport_id, policy_version_id, time_cutoff_offset_seconds,
     finalization_event_types, qualifying_change_criteria, governance_reference)
SELECT
    'MLB',
    'MLB-A3-v1',
    -900,
    '["play_locked"]'::jsonb,
    '{
        "starting_pitcher_replacement": true,
        "official_lineup_change_or_scratch": true,
        "postponement_cancellation_suspension": true,
        "schedule_change_minutes_gte": 10,
        "moneyline_implied_probability_move_pp_gte": 3,
        "weather_sustained_wind_mph_gte": 5,
        "weather_temperature_f_gte": 10,
        "weather_precip_probability_pp_gte": 20,
        "upstream_source_loss_or_staleness": true
    }'::jsonb,
    'PM-1007'
WHERE NOT EXISTS (
    SELECT 1 FROM oracle_sport_policies WHERE policy_version_id = 'MLB-A3-v1'
);

INSERT INTO oracle_sport_policy_active
    (sport_id, policy_version_id, governance_reference)
SELECT 'MLB', 'MLB-A3-v1', 'PM-1007'
WHERE NOT EXISTS (
    SELECT 1 FROM oracle_sport_policy_active
    WHERE sport_id = 'MLB' AND policy_version_id = 'MLB-A3-v1'
);
