-- Migration 011: Oracle Stage 7 final-analysis schema (Option A; PM-1047 / PM-1049).
-- Adds oracle_stage7_final_analysis (append-only frozen finalization of the Stage 5
-- verdict with Stage 6 observation provenance). Authorized by CWP-01/TAR Phase G Step 4
-- and PM-474 §7 (bounded working-tree change), per PM-1051. Migrations 001-010 remain
-- byte-immutable.
--
-- Option A discipline: the immutable Stage 5 scalar verdict is copied verbatim and bound
-- to its source through stage5_result_id + data_version_id. Stage 7 performs NO lineup-
-- adjusted calculation and NO confidence change. Pitchers remain PROBABLE. Finalization
-- does NOT establish official lineup confirmation, analytical freshness, or betting
-- readiness. observed_at measures Stage 6 retrieval/assessment time, not provider-origin
-- freshness; retrieval age is disclosed, never an eligibility gate. The cutoff relationship
-- (before/equal/after) is provenance only; no cutoff firing or cutoff-based eligibility.
--
-- One frozen final per game (UNIQUE game_run_id): the first finalization is frozen; a later
-- differing bound-input identity is reported as CHANGED_PROVENANCE and never rewrites or
-- creates a new final version. bound_input_identity is a deterministic hash over all bound
-- material inputs (Stage 5 result id + data version, policy version, scheduled cutoff, and
-- Stage 6 snapshot identity), not the Stage 5 version alone.
--
-- Rerunnable: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION+TRIGGER. No destructive DROP/ALTER.

CREATE TABLE IF NOT EXISTS oracle_stage7_final_analysis (
    id                        BIGSERIAL    PRIMARY KEY,
    game_run_id               TEXT         NOT NULL UNIQUE,   -- one frozen final per game
    slate_run_id              TEXT         NOT NULL,
    stage5_result_id          TEXT         NOT NULL,          -- immutable Stage 5 source binding
    data_version_id           TEXT         NOT NULL,
    policy_version_id         TEXT         NOT NULL,
    verdict                   TEXT         NOT NULL,          -- copied verbatim from Stage 5
    scheduled_cutoff_at       TIMESTAMPTZ  NOT NULL,
    -- Nullable in DDL per PM-1049 (no DDL change); first finalization REQUIRES a valid,
    -- non-future observed_at at runtime (else UNAVAILABLE_INPUTS, no row).
    stage6_snapshot_identity  TEXT,                           -- canonical OBSERVED_FULL provenance
    stage6_observed_at        TIMESTAMPTZ,                    -- Stage 6 retrieval/assessment time
    cutoff_relationship       TEXT
        CHECK (cutoff_relationship IS NULL OR cutoff_relationship IN ('before', 'equal', 'after')),
    bound_input_identity      TEXT         NOT NULL,          -- hash over all bound inputs
    limitations               JSONB        NOT NULL,          -- honest evidence limitations
    assessment_at             TIMESTAMPTZ  NOT NULL,          -- Stage 7 finalization time
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_stage7_final_analysis_slate_run_id
    ON oracle_stage7_final_analysis (slate_run_id);

-- Append-only enforcement (mirrors migrations 007-010)
CREATE OR REPLACE FUNCTION oracle_stage7_final_analysis_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_stage7_final_analysis is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_stage7_final_analysis_append_only
    BEFORE UPDATE OR DELETE ON oracle_stage7_final_analysis
    FOR EACH ROW EXECUTE FUNCTION oracle_stage7_final_analysis_append_only();
