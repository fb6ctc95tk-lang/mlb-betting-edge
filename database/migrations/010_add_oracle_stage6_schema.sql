-- Migration 010: Oracle Inc-3+ Stage 6 evidence-safe lineup-monitoring schema
-- Adds oracle_lineup_observations (append-only observed lineup snapshots).
-- Authorized by PM-1031 under PM-1029 (Option B, evidence-safe) / co-issued
-- CWP-01/TAR Step 4 + PM-474 §7. Migrations 001-009 remain byte-immutable.
--
-- Only canonical OBSERVED_FULL snapshots are persisted here. UNAVAILABLE and
-- PARTIAL outcomes are non-persistent (lifecycle-audit only). The lineup-status
-- CHECK deliberately EXCLUDES 'AUTHORITATIVELY_CONFIRMED': the current public
-- provider cannot prove official confirmation, so that status is never stored.
-- Structural completeness (a full 9-slot observed order) proves observation,
-- never official confirmation.
--
-- Rerunnable: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION+TRIGGER. No destructive DROP/ALTER.

CREATE TABLE IF NOT EXISTS oracle_lineup_observations (
    id                       BIGSERIAL    PRIMARY KEY,
    game_run_id              TEXT         NOT NULL,
    slate_run_id             TEXT         NOT NULL,
    snapshot_identity        TEXT         NOT NULL,
    observed_at              TIMESTAMPTZ  NOT NULL,
    source                   TEXT         NOT NULL,
    home_lineup              JSONB        NOT NULL,
    away_lineup              JSONB        NOT NULL,
    home_lineup_status       TEXT         NOT NULL
        CHECK (home_lineup_status IN ('UNAVAILABLE', 'PARTIAL', 'OBSERVED_FULL')),
    away_lineup_status       TEXT         NOT NULL
        CHECK (away_lineup_status IN ('UNAVAILABLE', 'PARTIAL', 'OBSERVED_FULL')),
    home_starting_pitcher    JSONB        NOT NULL,
    away_starting_pitcher    JSONB        NOT NULL,
    policy_version_id        TEXT         NOT NULL,
    change_detected          BOOLEAN      NOT NULL,
    change_evidence          JSONB        NOT NULL,
    prior_snapshot_identity  TEXT,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_oracle_lineup_obs_game_snapshot
        UNIQUE (game_run_id, snapshot_identity)
);

CREATE INDEX IF NOT EXISTS idx_oracle_lineup_observations_game_run_id
    ON oracle_lineup_observations (game_run_id);

CREATE INDEX IF NOT EXISTS idx_oracle_lineup_observations_slate_run_id
    ON oracle_lineup_observations (slate_run_id);

-- Append-only enforcement (mirrors migrations 007-009)
CREATE OR REPLACE FUNCTION oracle_lineup_observations_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_lineup_observations is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_lineup_observations_append_only
    BEFORE UPDATE OR DELETE ON oracle_lineup_observations
    FOR EACH ROW EXECUTE FUNCTION oracle_lineup_observations_append_only();
