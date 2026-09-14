-- Migration 015 — Oracle Market-Odds Observation store
-- (PM-1183 / PM-1185 / PM-1187 finalized contract, implemented under PM-1189).
-- Run once against the live database:
--
--   psql $DATABASE_URL -f database/migrations/015_add_oracle_market_odds_observations.sql
--
-- Creates an append-only, play-independent market-odds observation store.
-- Scope of this increment: TEST_FIXTURE observations only. Reserved provenance
-- classes (AUTHENTICATED_HISTORICAL, LIVE_PROVIDER) are enumerated but inert
-- (blocked by ck_moo_admission). Closing-line selection, CLV, provider/network,
-- attribution, and Stage 10 are NOT part of this migration.
--
-- Identity model:
--   * Eight-field coordinate:
--       (game_run_id, sportsbook, market, selected_side, price_format,
--        observed_at, source, data_origin)
--   * Multiple ROOTs (supersedes_observation_id IS NULL) may coexist at one
--     coordinate when price differs (independent roots -> coordinate CONFLICT at read).
--   * Exact-root replay: identical coordinate + price as a root is deduplicated
--     by ux_moo_root_exact.
--   * Each root anchors an independent, strictly-linear correction chain; a
--     correction matches all eight coordinate fields, references its current head,
--     changes only price, and there is at most one child per predecessor
--     (ux_moo_one_child).
--
-- Time model:
--   * ingested_at is FORCED by a BEFORE INSERT trigger to clock_timestamp()
--     (true row-ingestion wall clock, not transaction-start); any supplied value
--     is discarded. Strict ck_moo_observed_not_future rejects future observations.
--
-- Append-only: UPDATE and DELETE raise; corrections are new appended rows.
-- Rerunnable: CREATE ... IF NOT EXISTS / CREATE OR REPLACE (no destructive step).

CREATE TABLE IF NOT EXISTS oracle_market_odds_observations (
    observation_id            BIGSERIAL       PRIMARY KEY,
    game_run_id               VARCHAR         NOT NULL
        REFERENCES oracle_game_analyses(game_run_id) ON DELETE RESTRICT,
    sportsbook                VARCHAR         NOT NULL,
    market                    VARCHAR         NOT NULL,
    selected_side             VARCHAR         NOT NULL,
    price_format              VARCHAR         NOT NULL,
    price                     INTEGER         NOT NULL,
    source                    VARCHAR         NOT NULL,
    data_origin               VARCHAR         NOT NULL,
    observed_at               TIMESTAMPTZ     NOT NULL,
    ingested_at               TIMESTAMPTZ     NOT NULL,   -- forced by trigger; no DEFAULT
    supersedes_observation_id BIGINT
        REFERENCES oracle_market_odds_observations(observation_id) ON DELETE RESTRICT,
    correction_reason         VARCHAR,

    CONSTRAINT ck_moo_market_ml          CHECK (market = 'ML'),
    CONSTRAINT ck_moo_side_ml            CHECK (selected_side IN ('home', 'away')),
    CONSTRAINT ck_moo_price_format       CHECK (price_format = 'american'),
    CONSTRAINT ck_moo_american_domain    CHECK (price <= -100 OR price >= 100),
    CONSTRAINT ck_moo_origin_domain      CHECK (data_origin IN
                                           ('TEST_FIXTURE', 'AUTHENTICATED_HISTORICAL', 'LIVE_PROVIDER')),
    CONSTRAINT ck_moo_admission          CHECK (data_origin = 'TEST_FIXTURE'),
    CONSTRAINT ck_moo_source_fixture     CHECK (source = 'market_odds_fixture'),
    CONSTRAINT ck_moo_source_origin_pair CHECK (source <> 'market_odds_fixture'
                                           OR data_origin = 'TEST_FIXTURE'),
    CONSTRAINT ck_moo_sportsbook_token   CHECK (sportsbook ~ '^[A-Z0-9_]+$'),
    CONSTRAINT ck_moo_no_self_supersede  CHECK (supersedes_observation_id IS NULL
                                           OR supersedes_observation_id <> observation_id),
    CONSTRAINT ck_moo_observed_not_future CHECK (observed_at <= ingested_at)
);

-- Exact-root replay arbiter: eight coordinate fields + price, roots only.
-- Same coordinate + same price as a root collides (replay); differing price coexists.
CREATE UNIQUE INDEX IF NOT EXISTS ux_moo_root_exact
    ON oracle_market_odds_observations
    (game_run_id, sportsbook, market, selected_side, price_format, observed_at,
     source, data_origin, price)
    WHERE supersedes_observation_id IS NULL;

-- One child per predecessor: strictly-linear lineage, no branching.
CREATE UNIQUE INDEX IF NOT EXISTS ux_moo_one_child
    ON oracle_market_odds_observations (supersedes_observation_id)
    WHERE supersedes_observation_id IS NOT NULL;

-- Read helper for coordinate lookups (independent-root heads / CONFLICT read).
CREATE INDEX IF NOT EXISTS ix_moo_coordinate
    ON oracle_market_odds_observations
    (game_run_id, sportsbook, market, selected_side, price_format, observed_at,
     source, data_origin);

-- Append-only enforcement: INSERT permitted; UPDATE/DELETE raise and roll back.
CREATE OR REPLACE FUNCTION oracle_market_odds_observations_append_only()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'oracle_market_odds_observations is append-only: % on observation_id % is not permitted',
        TG_OP,
        OLD.observation_id;
END;
$$;

CREATE OR REPLACE TRIGGER enforce_moo_append_only
    BEFORE UPDATE OR DELETE ON oracle_market_odds_observations
    FOR EACH ROW EXECUTE FUNCTION oracle_market_odds_observations_append_only();

-- Forced ingestion time: unconditionally overwrite any supplied ingested_at with
-- the true row-insertion wall clock, BEFORE constraints (so ck_moo_observed_not_future
-- evaluates against the real time and future-dated observations cannot be admitted).
CREATE OR REPLACE FUNCTION oracle_moo_ingest_time()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    NEW.ingested_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER enforce_moo_ingest_time
    BEFORE INSERT ON oracle_market_odds_observations
    FOR EACH ROW EXECUTE FUNCTION oracle_moo_ingest_time();

-- Lineage fail-closed backstop: for a correction (supersedes NOT NULL) reject
-- missing predecessor (malformed), any coordinate-field mismatch (cross-lineage),
-- and a predecessor that already has a child (branch / stale head). Identical-child
-- replay never reaches INSERT (the recorder returns it first), so a genuine INSERT
-- against a predecessor-with-child is always a real conflict.
CREATE OR REPLACE FUNCTION oracle_moo_lineage_guard()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
DECLARE
    p oracle_market_odds_observations%ROWTYPE;
BEGIN
    IF NEW.supersedes_observation_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO p
    FROM oracle_market_odds_observations
    WHERE observation_id = NEW.supersedes_observation_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'moo lineage malformed: predecessor % not found', NEW.supersedes_observation_id;
    END IF;

    IF (NEW.game_run_id, NEW.sportsbook, NEW.market, NEW.selected_side,
        NEW.price_format, NEW.observed_at, NEW.source, NEW.data_origin)
       IS DISTINCT FROM
       (p.game_run_id, p.sportsbook, p.market, p.selected_side,
        p.price_format, p.observed_at, p.source, p.data_origin) THEN
        RAISE EXCEPTION
            'moo cross-lineage correction rejected for predecessor %', p.observation_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM oracle_market_odds_observations
        WHERE supersedes_observation_id = p.observation_id
    ) THEN
        RAISE EXCEPTION
            'moo branch/stale-head supersession rejected for predecessor %', p.observation_id;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER enforce_moo_lineage
    BEFORE INSERT ON oracle_market_odds_observations
    FOR EACH ROW EXECUTE FUNCTION oracle_moo_lineage_guard();
