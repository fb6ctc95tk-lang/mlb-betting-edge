-- Migration 016 — Oracle Stage-2 underlying-game admission claim + window ledger
-- (PM-1263 → PM-1269, accepted by PM-1270; implemented under PM-1271).
--
--   psql "$DSN" -f database/migrations/016_add_oracle_underlying_admission_claim_and_window.sql
--
-- Adds two append-only tables enforcing the ratified admission invariants over
-- the Stable Underlying Identity (SUI) = (source_namespace, sport_id, game_pk):
--
--   1. oracle_underlying_admission_claim  — D-4: at most ONE official Stage-8
--      admission per underlying game across all slate revisions/business dates.
--      Enforced by UNIQUE(source_namespace, sport_id, game_pk).
--
--   2. oracle_underlying_admission_window — D-5: durable per-SUI admission-window
--      history so an expired-unused window cannot be reopened behind a new
--      game_run_id. Carries the frozen Stage-2 timing binding (scheduled start,
--      policy version, normalized cutoff offset, calculated cutoff, window
--      identity) that Stage 5 consumes/reconciles.
--
-- Both tables are append-only (UPDATE/DELETE blocked by trigger), mirroring
-- migrations 009/012/013. Migrations 001–015 remain byte-immutable. Rerunnable:
-- CREATE TABLE/INDEX IF NOT EXISTS, CREATE OR REPLACE FUNCTION+TRIGGER, and
-- idempotent guarded backfill. No destructive DROP or existing-column ALTER.
--
-- Namespaces: 'mlb-statsapi' (live) and 'fixture' (deterministic tests / legacy
-- fixture history). They never collide. This migration NEVER assigns live
-- ('mlb-statsapi') provenance to ambiguous historical rows (PM-1269 §4).


-- -------------------------------------------------------------
-- TABLE 1: oracle_underlying_admission_claim  (D-4)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_underlying_admission_claim (
    id                BIGSERIAL    PRIMARY KEY,
    source_namespace  TEXT         NOT NULL,
    sport_id          INTEGER      NOT NULL,
    game_pk           TEXT         NOT NULL,
    game_run_id       TEXT         NOT NULL,      -- winning run (provenance)
    slate_run_id      TEXT         NOT NULL,
    claimed_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_oracle_uac_sui UNIQUE (source_namespace, sport_id, game_pk)
);

CREATE INDEX IF NOT EXISTS idx_oracle_uac_game_run_id
    ON oracle_underlying_admission_claim (game_run_id);

CREATE OR REPLACE FUNCTION oracle_underlying_admission_claim_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_underlying_admission_claim is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_uac_append_only
    BEFORE UPDATE OR DELETE ON oracle_underlying_admission_claim
    FOR EACH ROW EXECUTE FUNCTION oracle_underlying_admission_claim_append_only();


-- -------------------------------------------------------------
-- TABLE 2: oracle_underlying_admission_window  (D-5 + frozen binding)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oracle_underlying_admission_window (
    id                         BIGSERIAL    PRIMARY KEY,
    source_namespace           TEXT         NOT NULL,
    sport_id                   INTEGER      NOT NULL,
    game_pk                    TEXT         NOT NULL,
    game_run_id                TEXT         NOT NULL,
    slate_run_id               TEXT         NOT NULL,
    scheduled_start_at         TIMESTAMPTZ  NOT NULL,   -- frozen scheduled start (first pitch)
    cutoff_offset              INTERVAL     NOT NULL,   -- normalized policy offset
    scheduled_cutoff_at        TIMESTAMPTZ  NOT NULL,   -- start + offset (frozen)
    policy_version_id          TEXT         NOT NULL,
    window_identity            TEXT         NOT NULL,
    window_action              TEXT         NOT NULL
        CHECK (window_action IN (
            'window_established',
            'window_superseded',
            'window_blocked_prior_expired',
            'window_blocked_prior_admission',
            'window_blocked_stale_observation'
        )),
    superseded_by_game_run_id  TEXT,
    retrieved_at               TIMESTAMPTZ,             -- provider-owned local order; NULL for legacy backfill
    decision_at                TIMESTAMPTZ  NOT NULL,   -- DB clock_timestamp() at the decision (provenance)
    created_at                 TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oracle_uaw_sui
    ON oracle_underlying_admission_window (source_namespace, sport_id, game_pk);
CREATE INDEX IF NOT EXISTS idx_oracle_uaw_game_run_id
    ON oracle_underlying_admission_window (game_run_id);

CREATE OR REPLACE FUNCTION oracle_underlying_admission_window_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_underlying_admission_window is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_uaw_append_only
    BEFORE UPDATE OR DELETE ON oracle_underlying_admission_window
    FOR EACH ROW EXECUTE FUNCTION oracle_underlying_admission_window_append_only();


-- -------------------------------------------------------------
-- LEGACY COMPATIBILITY / BACKFILL  (PM-1269 §4)
--
-- Existing Stage-8/9 admissions and authoritative cutoffs predate this
-- mechanism. Deployment must not create empty tables and pretend that history
-- does not exist. The ONLY Stage-2 source to date is the fixture provider
-- (PM-1261/1263: run_stage_2 called load_phase1_fixtures), so all legacy
-- game_run_ids are fixture-origin and are backfilled under the 'fixture'
-- namespace. Live ('mlb-statsapi') provenance is NEVER inferred.
--
-- FAIL CLOSED on ambiguous provenance: if any legacy admission or cutoff row
-- has a game_run_id from which a trailing numeric gamePk cannot be parsed, the
-- migration aborts rather than guessing.
-- -------------------------------------------------------------
DO $backfill$
DECLARE
    ambiguous_count INTEGER;
    conflict_count INTEGER;
    inconsistent_count INTEGER;
    now_instant TIMESTAMPTZ := clock_timestamp();
BEGIN
    -- Guard 1 (ambiguous provenance): every legacy admission / cutoff game_run_id must end in a
    -- gamePk. Unparseable provenance is never guessed.
    SELECT COUNT(*) INTO ambiguous_count FROM (
        SELECT game_run_id FROM oracle_stage8_activation_window
        WHERE game_run_id !~ '-[0-9]+$'
        UNION
        SELECT game_run_id FROM oracle_scheduled_cutoffs
        WHERE game_run_id !~ '-[0-9]+$'
    ) AS ambiguous;
    IF ambiguous_count > 0 THEN
        RAISE EXCEPTION
            'migration 016 fail-closed: % legacy row(s) with unparseable game_run_id provenance; refusing to guess',
            ambiguous_count;
    END IF;

    -- Guard 2 (conflicting legacy admissions): if two or more DISTINCT legacy Stage-8 admissions
    -- map to the same underlying SUI (fixture, 1, gamePk), a single valid D-4 claim cannot be
    -- chosen. Fail closed rather than silently retaining one (never ON CONFLICT DO NOTHING).
    SELECT COUNT(*) INTO conflict_count FROM (
        SELECT substring(game_run_id from '([0-9]+)$') AS game_pk
        FROM oracle_stage8_activation_window
        GROUP BY 1
        HAVING COUNT(DISTINCT game_run_id) > 1
    ) AS conflicting;
    IF conflict_count > 0 THEN
        RAISE EXCEPTION
            'migration 016 fail-closed: % underlying game(s) have conflicting legacy Stage-8 admissions (multiple game_run_ids per SUI); refusing to resolve arbitrarily',
            conflict_count;
    END IF;

    -- Guard 3 (existing claim inconsistent with source): a pre-existing fixture claim for a gamePk
    -- that HAS legacy admissions, but whose game_run_id is not one of them, contradicts the source
    -- history. Fail closed. (An identical already-applied claim — same game_run_id — is accepted as
    -- idempotent replay by Guard-passing + the NOT EXISTS insert below.)
    SELECT COUNT(*) INTO inconsistent_count
    FROM oracle_underlying_admission_claim c
    WHERE c.source_namespace = 'fixture' AND c.sport_id = 1
      AND EXISTS (
          SELECT 1 FROM oracle_stage8_activation_window a
          WHERE substring(a.game_run_id from '([0-9]+)$') = c.game_pk)
      AND NOT EXISTS (
          SELECT 1 FROM oracle_stage8_activation_window a
          WHERE a.game_run_id = c.game_run_id
            AND substring(a.game_run_id from '([0-9]+)$') = c.game_pk);
    IF inconsistent_count > 0 THEN
        RAISE EXCEPTION
            'migration 016 fail-closed: % existing fixture claim(s) inconsistent with legacy Stage-8 admission history',
            inconsistent_count;
    END IF;

    -- D-4 backfill: one claim per legacy Stage-8 admission (fixture namespace). Conflicts and
    -- inconsistencies are already excluded above, so a NOT EXISTS guard is deterministic and
    -- idempotent on repeat application (identical already-applied → skipped, no error).
    INSERT INTO oracle_underlying_admission_claim
        (source_namespace, sport_id, game_pk, game_run_id, slate_run_id, claimed_at)
    SELECT 'fixture', 1,
           substring(a.game_run_id from '([0-9]+)$'),
           a.game_run_id, a.slate_run_id, now_instant
    FROM oracle_stage8_activation_window a
    WHERE NOT EXISTS (
        SELECT 1 FROM oracle_underlying_admission_claim c
        WHERE c.source_namespace = 'fixture' AND c.sport_id = 1
          AND c.game_pk = substring(a.game_run_id from '([0-9]+)$'));

    -- D-5 backfill: an authoritative window for EVERY legacy cutoff, including
    -- expired-unused windows (no Stage-8 admission required). Idempotent.
    INSERT INTO oracle_underlying_admission_window
        (source_namespace, sport_id, game_pk, game_run_id, slate_run_id,
         scheduled_start_at, cutoff_offset, scheduled_cutoff_at, policy_version_id,
         window_identity, window_action, superseded_by_game_run_id,
         retrieved_at, decision_at)
    SELECT 'fixture', 1,
           substring(c.game_run_id from '([0-9]+)$'),
           c.game_run_id, c.slate_run_id,
           g.first_pitch_time,
           (c.scheduled_cutoff_at - g.first_pitch_time),
           c.scheduled_cutoff_at, c.policy_version_id,
           'S2W-legacy-' || md5(c.game_run_id),
           'window_established', NULL,
           NULL,                 -- legacy retrieval time unknown; never fabricated
           now_instant           -- provenance of recording, not historical decision evidence
    FROM oracle_scheduled_cutoffs c
    JOIN oracle_game_analyses g ON g.game_run_id = c.game_run_id
    WHERE NOT EXISTS (
        SELECT 1 FROM oracle_underlying_admission_window w
        WHERE w.game_run_id = c.game_run_id
          AND w.window_action = 'window_established'
    );
END;
$backfill$;
