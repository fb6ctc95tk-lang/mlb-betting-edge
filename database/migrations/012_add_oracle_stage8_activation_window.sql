-- Migration 012: Oracle Stage 8 activation-window schema (C1 FULL; PM-1067).
-- Immutable, append-only per-game procedural admission into the activation window,
-- bound to the frozen Stage 7 evidence identity. Admission establishes NO bet, edge,
-- official confirmation, freshness, or betting readiness, and computes no analytical
-- value. First admission requires assessment_time < the frozen scheduled_cutoff_at
-- (timezone-aware). Historical admission is not perpetual permission after cutoff; no
-- automatic closing, no cutoff firing, no scheduler.
--
-- Authorized by CWP-01/TAR Phase G Step 4 and PM-474 §7 (bounded working-tree change),
-- per PM-1073. Migrations 001-011 remain byte-immutable. Rerunnable:
-- CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION+TRIGGER. No destructive DROP/ALTER.
--
-- assessment_at stores the fresh, timezone-aware decision_time captured immediately
-- before the first-admission write (PM-1069/PM-1071); a later commit does not re-gate.
-- For admitted rows cutoff_relationship is always 'before' (the C4 gate); the column
-- exists for provenance parity with Stage 7. Divergence reporting reuses the existing
-- oracle_lifecycle_audit table (no new audit table, no new event type, no state change).

CREATE TABLE IF NOT EXISTS oracle_stage8_activation_window (
    id                          BIGSERIAL    PRIMARY KEY,
    game_run_id                 TEXT         NOT NULL UNIQUE,   -- one admission per game
    slate_run_id                TEXT         NOT NULL,
    stage7_bound_input_identity TEXT         NOT NULL,          -- frozen Stage 7 evidence bound
    activation_identity         TEXT         NOT NULL,          -- S8A- hash (game + S7 identity)
    scheduled_cutoff_at         TIMESTAMPTZ  NOT NULL,          -- frozen-source (from Stage 7 record)
    cutoff_relationship         TEXT
        CHECK (cutoff_relationship IS NULL OR cutoff_relationship IN ('before','equal','after')),
    limitations                 JSONB        NOT NULL,          -- honest admission limitations
    assessment_at               TIMESTAMPTZ  NOT NULL,          -- trusted decision-point clock
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_stage8_activation_window_slate_run_id
    ON oracle_stage8_activation_window (slate_run_id);

CREATE OR REPLACE FUNCTION oracle_stage8_activation_window_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_stage8_activation_window is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_stage8_activation_window_append_only
    BEFORE UPDATE OR DELETE ON oracle_stage8_activation_window
    FOR EACH ROW EXECUTE FUNCTION oracle_stage8_activation_window_append_only();
