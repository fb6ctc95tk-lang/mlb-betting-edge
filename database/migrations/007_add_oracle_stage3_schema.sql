-- Migration 007: Oracle Inc-1 Stage 3 schema additions
-- Adds oracle_preliminary_data (Stage 3 data store) and
-- oracle_lifecycle_audit (append-only stage lifecycle audit log).
-- Authorized by PM-773 / Authorities A+B; scope v3 SHA C0BB3881...

-- ---------------------------------------------------------------------------
-- oracle_preliminary_data: one row per successful Stage 3 data gather
-- ---------------------------------------------------------------------------

CREATE TABLE oracle_preliminary_data (
    id               BIGSERIAL    PRIMARY KEY,
    game_run_id      TEXT         NOT NULL,
    slate_run_id     TEXT         NOT NULL,
    data_version_id  TEXT         NOT NULL UNIQUE,
    game_id          TEXT         NOT NULL,
    gathered_at      TIMESTAMPTZ  NOT NULL,
    raw_payload      JSONB        NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oracle_preliminary_data_game_run_id
    ON oracle_preliminary_data (game_run_id);

CREATE INDEX idx_oracle_preliminary_data_slate_run_id
    ON oracle_preliminary_data (slate_run_id);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION oracle_preliminary_data_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_preliminary_data is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_preliminary_data_append_only
    BEFORE UPDATE OR DELETE ON oracle_preliminary_data
    FOR EACH ROW EXECUTE FUNCTION oracle_preliminary_data_append_only();

-- ---------------------------------------------------------------------------
-- oracle_lifecycle_audit: append-only log of stage lifecycle events
-- ---------------------------------------------------------------------------

CREATE TABLE oracle_lifecycle_audit (
    id           BIGSERIAL    PRIMARY KEY,
    game_run_id  TEXT         NOT NULL,
    slate_run_id TEXT         NOT NULL,
    stage        TEXT         NOT NULL,
    event        TEXT         NOT NULL,
    detail       TEXT,
    recorded_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oracle_lifecycle_audit_game_run_id
    ON oracle_lifecycle_audit (game_run_id);

CREATE INDEX idx_oracle_lifecycle_audit_slate_run_id
    ON oracle_lifecycle_audit (slate_run_id);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION oracle_lifecycle_audit_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_lifecycle_audit is append-only: % on id % is not permitted',
        TG_OP, OLD.id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_lifecycle_audit_append_only
    BEFORE UPDATE OR DELETE ON oracle_lifecycle_audit
    FOR EACH ROW EXECUTE FUNCTION oracle_lifecycle_audit_append_only();
