-- Migration 008: Oracle Inc-2 Stage 4 schema additions
-- Adds oracle_ecf_results (Structural ECF v1 score store; append-only).
-- Authorized by PM-867 / Authorities A+B; scope SHA F3BF406F...
-- OPEN-SCHEMA resolution from PM-855.

-- ---------------------------------------------------------------------------
-- oracle_ecf_results: one row per successful Stage 4 ECF calculation
-- ---------------------------------------------------------------------------

CREATE TABLE oracle_ecf_results (
    ecf_result_id    TEXT             PRIMARY KEY,
    game_run_id      TEXT             NOT NULL,
    data_version_id  TEXT             NOT NULL,
    ecf_score        DOUBLE PRECISION NOT NULL CHECK (ecf_score >= 0.0 AND ecf_score <= 1.0),
    component_scores JSONB            NOT NULL,
    model_version    TEXT             NOT NULL,
    computed_at      TIMESTAMPTZ      NOT NULL
);

CREATE INDEX idx_oracle_ecf_results_game_run_id
    ON oracle_ecf_results (game_run_id);

CREATE INDEX idx_oracle_ecf_results_data_version_id
    ON oracle_ecf_results (data_version_id);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION oracle_ecf_results_append_only()
    RETURNS TRIGGER LANGUAGE plpgsql
AS $func$
BEGIN
    RAISE EXCEPTION
        'oracle_ecf_results is append-only: % on id % is not permitted',
        TG_OP, OLD.ecf_result_id;
END;
$func$;

CREATE OR REPLACE TRIGGER enforce_ecf_results_append_only
    BEFORE UPDATE OR DELETE ON oracle_ecf_results
    FOR EACH ROW EXECUTE FUNCTION oracle_ecf_results_append_only();
