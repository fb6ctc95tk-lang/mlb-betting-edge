-- Migration 013: Oracle Stage 9 pregame-lock schema (FULL immutable per-game lock;
-- PM-1089 as corrected by PM-1091, finalized by PM-1092).
-- Immutable, append-only per-game pregame lock, bound to the frozen Stage-8 admission
-- provenance (activation identity) and the frozen Stage-7 bound input identity. The lock
-- establishes NO bet, edge, official confirmation, freshness, or betting readiness, and
-- computes no analytical value. A lock is written only when the fresh post-wait decision_at
-- is strictly before the frozen scheduled_cutoff_at (timezone-aware); equality/after is
-- INELIGIBLE and writes no lock. Historical lock is not perpetual permission after cutoff;
-- no automatic closing, no cutoff firing, no scheduler.
--
-- Authorized by CWP-01/TAR Phase G Step 4 and a scoped PM-474 §7 supersession for this
-- package's seven paths (per PM-1093). Migrations 001-012 remain byte-immutable. Rerunnable:
-- CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION+TRIGGER. No destructive DROP/ALTER.
--
-- decision_at stores the fresh, timezone-aware decision_time captured immediately before the
-- lock write, sampled AFTER acquiring the slate-row lock (post-wait); a later commit does not
-- re-gate. For locked rows cutoff_relationship is always 'before' (the strict freeze boundary);
-- the column exists for provenance parity with Stage 8. Divergence reporting reuses the existing
-- oracle_lifecycle_audit table (no new audit table, no new event type, no state change).

CREATE TABLE IF NOT EXISTS oracle_stage9_pregame_lock (
    id                          BIGSERIAL    PRIMARY KEY,
    game_run_id                 TEXT         NOT NULL UNIQUE,   -- one lock per game
    slate_run_id                TEXT         NOT NULL,
    activation_identity         TEXT         NOT NULL,          -- frozen Stage-8 admission bound
    stage7_bound_input_identity TEXT         NOT NULL,          -- frozen Stage-7 evidence bound
    lock_identity               TEXT         NOT NULL,          -- S9L- hash (game + S8A + S7 identity)
    scheduled_cutoff_at         TIMESTAMPTZ  NOT NULL,          -- frozen-source (from Stage-8 admission)
    cutoff_relationship         TEXT
        CHECK (cutoff_relationship IS NULL OR cutoff_relationship IN ('before','equal','after')),
    limitations                 JSONB        NOT NULL,          -- honest lock limitations
    decision_at                 TIMESTAMPTZ  NOT NULL,          -- post-wait decision-point clock
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_stage9_pregame_lock_slate_run_id
    ON oracle_stage9_pregame_lock (slate_run_id);

CREATE OR REPLACE FUNCTION oracle_stage9_pregame_lock_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_stage9_pregame_lock is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_stage9_pregame_lock_append_only
    BEFORE UPDATE OR DELETE ON oracle_stage9_pregame_lock
    FOR EACH ROW EXECUTE FUNCTION oracle_stage9_pregame_lock_append_only();
