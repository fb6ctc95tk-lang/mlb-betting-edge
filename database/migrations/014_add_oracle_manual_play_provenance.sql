-- Migration 014: Oracle manual paper-play provenance
-- (PM-1131 / PM-1133 / PM-1135 / PM-1137, implemented under PM-1139).
--
-- Adds authoritative but migration-compatible MANUAL provenance to oracle_plays:
--   * origin: NULLABLE, NO DEFAULT, NO BACKFILL. Pre-existing rows (none exist)
--     remain NULL ("unspecified/legacy") and are never fabricated as MANUAL.
--     No exhaustive value CHECK — the origin domain is intentionally NOT enumerated
--     (nonmanual/future origins are neither required nor excluded).
--   * MANUAL-scoped American-odds domain CHECK (applies only when origin = 'MANUAL').
--   * MANUAL-scoped identity unique index (game_run_id, market, selected_side).
--
-- The application layer (backend/oracle/manual_play.py) always writes origin='MANUAL'.
-- Migrations 001-013 remain byte-immutable. Rerunnable via IF NOT EXISTS / DO-guards.
-- oracle_plays is NOT append-only (settlement updates it later); no trigger added.

ALTER TABLE oracle_plays ADD COLUMN IF NOT EXISTS origin VARCHAR;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'oracle_plays_manual_odds_domain'
    ) THEN
        ALTER TABLE oracle_plays
            ADD CONSTRAINT oracle_plays_manual_odds_domain
            CHECK (
                origin IS DISTINCT FROM 'MANUAL'
                OR odds_at_nomination >= 100
                OR odds_at_nomination <= -100
            );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_plays_manual_identity
    ON oracle_plays (game_run_id, market, selected_side)
    WHERE origin = 'MANUAL';
