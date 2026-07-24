-- Migration 006 — add Oracle play events append-only trigger
-- Run once against the live database.
--
--   psql $DATABASE_URL -f database/migrations/006_add_oracle_append_only_triggers.sql
--
-- Creates a trigger function and trigger that enforce append-only
-- behavior on oracle_play_events. INSERT is permitted; UPDATE and
-- DELETE raise an exception and roll back the operation entirely.
--
-- R-3 policy: no row is written to oracle_immutability_audit by this
-- trigger. The rejected statement's transaction rolls back in full,
-- making any in-transaction write non-durable. Durable violation
-- auditing is deferred to a separately authorized future design.
--
-- Idempotency: CREATE OR REPLACE is the PostgreSQL equivalent of
-- IF NOT EXISTS for functions and triggers (PG 14+). Rerunning this
-- migration replaces the function and trigger in place with no schema
-- change.

CREATE OR REPLACE FUNCTION oracle_play_events_append_only()
    RETURNS TRIGGER
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'oracle_play_events is append-only: % on event_id % is not permitted',
        TG_OP,
        OLD.event_id;
END;
$$;

CREATE OR REPLACE TRIGGER enforce_play_events_append_only
    BEFORE UPDATE OR DELETE ON oracle_play_events
    FOR EACH ROW EXECUTE FUNCTION oracle_play_events_append_only();
