"""Oracle Phase 1 WP-2 append-only enforcement tests.

Requires ORACLE_TEST_DATABASE_URL pointing to a disposable PostgreSQL
database with Migrations 005 and 006 applied. All tests are skipped
when the variable is absent so the CI suite can run without a live
database.

Per R-3 policy: the append-only trigger raises an exception and rolls
back the entire rejected transaction. No durable row is written to
oracle_immutability_audit by the trigger. Tests confirm this behavior
explicitly.

Covers:
  - Trigger function and trigger object existence
  - Trigger attachment, timing, and event coverage
  - INSERT permitted (trigger does not fire on INSERT)
  - UPDATE rejected by trigger; exception raised; row unchanged
  - DELETE rejected by trigger; exception raised; row remains present
  - Transaction rollback semantics after rejection
  - R-3: no durable audit row written to oracle_immutability_audit
  - Regression: existing Oracle schema tests continue to pass
  - Regression: existing platform tables unaffected
"""

import os

import psycopg2
import psycopg2.errors
import pytest

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set — Oracle WP-2 integration tests skipped",
)

_SLATE_RUN_ID = "ORACLE-20260101-WP2"


@pytest.fixture(scope="module")
def conn():
    connection = psycopg2.connect(_TEST_DB_URL)
    connection.autocommit = True
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def seed_slate_run(conn):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, run_started_at)
        VALUES (%s, '2026-01-01', 'initializing', NOW())
        """,
        (_SLATE_RUN_ID,),
    )
    cur.close()
    yield _SLATE_RUN_ID
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM oracle_slate_runs WHERE slate_run_id = %s",
        (_SLATE_RUN_ID,),
    )
    cur.close()


@pytest.fixture(scope="module")
def seed_event(conn, seed_slate_run):
    """Insert one oracle_play_events row for mutation-rejection tests.

    Teardown uses TRUNCATE rather than DELETE because DELETE on
    oracle_play_events is blocked by the append-only trigger.
    TRUNCATE bypasses row-level triggers in PostgreSQL (FOR EACH ROW
    triggers do not fire for TRUNCATE), so it is the correct cleanup
    mechanism in this context.
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, event_timestamp)
        VALUES ('slate_initialized', %s, NOW())
        RETURNING event_id
        """,
        (seed_slate_run,),
    )
    event_id = cur.fetchone()[0]
    cur.close()
    yield event_id
    cur = conn.cursor()
    cur.execute("TRUNCATE oracle_play_events")
    cur.close()


# ---------------------------------------------------------------------------
# Trigger object existence
# ---------------------------------------------------------------------------

def test_trigger_function_exists(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT routine_name
        FROM information_schema.routines
        WHERE routine_schema = 'public'
          AND routine_type = 'FUNCTION'
          AND routine_name = 'oracle_play_events_append_only'
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Trigger function oracle_play_events_append_only not found"


def test_trigger_exists(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE event_object_schema = 'public'
          AND event_object_table = 'oracle_play_events'
          AND trigger_name = 'enforce_play_events_append_only'
        LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Trigger enforce_play_events_append_only not found"


def test_trigger_is_attached_to_oracle_play_events(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT event_object_table
        FROM information_schema.triggers
        WHERE trigger_name = 'enforce_play_events_append_only'
          AND event_object_schema = 'public'
        LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert row[0] == "oracle_play_events"


def test_trigger_timing_is_before(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT action_timing
        FROM information_schema.triggers
        WHERE event_object_table = 'oracle_play_events'
          AND trigger_name = 'enforce_play_events_append_only'
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert row[0] == "BEFORE"


def test_trigger_covers_update(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT event_manipulation
        FROM information_schema.triggers
        WHERE event_object_table = 'oracle_play_events'
          AND trigger_name = 'enforce_play_events_append_only'
          AND event_manipulation = 'UPDATE'
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Trigger does not cover UPDATE"


def test_trigger_covers_delete(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT event_manipulation
        FROM information_schema.triggers
        WHERE event_object_table = 'oracle_play_events'
          AND trigger_name = 'enforce_play_events_append_only'
          AND event_manipulation = 'DELETE'
        """
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Trigger does not cover DELETE"


# ---------------------------------------------------------------------------
# INSERT permitted
# ---------------------------------------------------------------------------

def test_insert_succeeds(conn, seed_slate_run):
    """INSERT must not fire the trigger and must complete without error."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_play_events
            (event_type, slate_run_id, event_timestamp)
        VALUES ('schedule_retrieved', %s, NOW())
        RETURNING event_id
        """,
        (seed_slate_run,),
    )
    event_id = cur.fetchone()[0]
    cur.close()
    assert isinstance(event_id, int)
    assert event_id > 0


# ---------------------------------------------------------------------------
# UPDATE protection
# ---------------------------------------------------------------------------

def test_update_raises_exception(conn, seed_event):
    """UPDATE on oracle_play_events must raise an exception."""
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute(
            "UPDATE oracle_play_events SET event_type = 'schedule_retrieved' WHERE event_id = %s",
            (seed_event,),
        )
    cur.close()


def test_update_exception_message_identifies_operation(conn, seed_event):
    """The exception message must stably identify the rejected operation."""
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE oracle_play_events SET event_type = 'schedule_retrieved' WHERE event_id = %s",
            (seed_event,),
        )
        pytest.fail("Expected RaiseException was not raised")
    except psycopg2.errors.RaiseException as exc:
        assert "append-only" in str(exc).lower()
        assert "UPDATE" in str(exc)
    finally:
        cur.close()


def test_update_row_unchanged_after_rejection(conn, seed_event):
    """After a rejected UPDATE, the original row must remain unchanged."""
    original_event_type = "slate_initialized"
    cur = conn.cursor()

    # Attempt UPDATE — trigger rejects it and rolls back the statement.
    try:
        cur.execute(
            "UPDATE oracle_play_events SET event_type = 'schedule_retrieved' WHERE event_id = %s",
            (seed_event,),
        )
    except psycopg2.errors.RaiseException:
        pass  # expected; autocommit means the statement's transaction already rolled back

    # Row must still hold the original value.
    cur.execute(
        "SELECT event_type FROM oracle_play_events WHERE event_id = %s",
        (seed_event,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Row missing after rejected UPDATE"
    assert row[0] == original_event_type, (
        f"Row was mutated: expected {original_event_type!r}, got {row[0]!r}"
    )


# ---------------------------------------------------------------------------
# DELETE protection
# ---------------------------------------------------------------------------

def test_delete_raises_exception(conn, seed_event):
    """DELETE on oracle_play_events must raise an exception."""
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute(
            "DELETE FROM oracle_play_events WHERE event_id = %s",
            (seed_event,),
        )
    cur.close()


def test_delete_exception_message_identifies_operation(conn, seed_event):
    """The exception message must stably identify the rejected operation."""
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM oracle_play_events WHERE event_id = %s",
            (seed_event,),
        )
        pytest.fail("Expected RaiseException was not raised")
    except psycopg2.errors.RaiseException as exc:
        assert "append-only" in str(exc).lower()
        assert "DELETE" in str(exc)
    finally:
        cur.close()


def test_row_present_after_delete_rejection(conn, seed_event):
    """After a rejected DELETE, the row must still be present."""
    cur = conn.cursor()

    # Attempt DELETE — trigger rejects it and rolls back the statement.
    try:
        cur.execute(
            "DELETE FROM oracle_play_events WHERE event_id = %s",
            (seed_event,),
        )
    except psycopg2.errors.RaiseException:
        pass  # expected

    # Row must still exist.
    cur.execute(
        "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
        (seed_event,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None, "Row was deleted despite trigger rejection"
    assert row[0] == seed_event


# ---------------------------------------------------------------------------
# R-3 behavior: no durable audit row written
# ---------------------------------------------------------------------------

def test_no_durable_audit_row_after_update_rejection(conn, seed_event):
    """Per R-3 policy: a rejected UPDATE rolls back entirely.

    No durable row is written to oracle_immutability_audit by the trigger.
    This test verifies that the audit table count is unchanged after a
    rejected UPDATE.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM oracle_immutability_audit")
    count_before = cur.fetchone()[0]

    try:
        cur.execute(
            "UPDATE oracle_play_events SET event_type = 'x' WHERE event_id = %s",
            (seed_event,),
        )
    except psycopg2.errors.RaiseException:
        pass

    cur.execute("SELECT COUNT(*) FROM oracle_immutability_audit")
    count_after = cur.fetchone()[0]
    cur.close()

    assert count_after == count_before, (
        f"R-3 violation: audit count changed from {count_before} to {count_after} "
        f"after a rejected UPDATE"
    )


def test_no_durable_audit_row_after_delete_rejection(conn, seed_event):
    """Per R-3 policy: a rejected DELETE rolls back entirely.

    No durable row is written to oracle_immutability_audit by the trigger.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM oracle_immutability_audit")
    count_before = cur.fetchone()[0]

    try:
        cur.execute(
            "DELETE FROM oracle_play_events WHERE event_id = %s",
            (seed_event,),
        )
    except psycopg2.errors.RaiseException:
        pass

    cur.execute("SELECT COUNT(*) FROM oracle_immutability_audit")
    count_after = cur.fetchone()[0]
    cur.close()

    assert count_after == count_before, (
        f"R-3 violation: audit count changed from {count_before} to {count_after} "
        f"after a rejected DELETE"
    )


# ---------------------------------------------------------------------------
# Regression: existing platform tables unaffected
# ---------------------------------------------------------------------------

def test_platform_tables_unaffected(conn):
    """Existing platform tables must remain present and accessible."""
    platform_tables = [
        "teams", "games", "starting_pitchers", "odds_history",
        "team_records", "game_weather", "team_bullpen_context", "team_injuries",
    ]
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (platform_tables,),
    )
    found = {row[0] for row in cur.fetchall()}
    cur.close()
    assert found == set(platform_tables), (
        f"Missing platform tables: {set(platform_tables) - found}"
    )
