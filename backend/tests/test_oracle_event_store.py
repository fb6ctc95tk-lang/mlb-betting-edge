"""Oracle Phase 1 WP-5 — Event Store tests.

Unit tests (Sections A–F) run without a database.
PostgreSQL integration tests (Section G) require ORACLE_TEST_DATABASE_URL
pointing to a disposable database with Migrations 005 and 006 applied.
Integration tests are skipped when the variable is absent.

Parameter order in record_event() INSERT params tuple:
    params[0] = event_type
    params[1] = slate_run_id
    params[2] = game_run_id
    params[3] = play_id
    params[4] = event_timestamp
    params[5] = payload_value (json.dumps(payload) or None)
"""

from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timezone

import pytest

from backend.oracle.event_store import _EVENT_TYPES, record_event
from backend.oracle.identifier_manager import InvalidConnectionStateError

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")

_requires_db = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set — WP-5 PostgreSQL integration tests skipped",
)

_VALID_SLATE_RUN_ID = "ORACLE-20260725-001"
_VALID_TIMESTAMP = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Unit test helpers
# ---------------------------------------------------------------------------

class _InsertMockCursor:
    """Tracks SQL execution; fetchone() returns a configurable event_id."""

    def __init__(self, event_id: int = 42) -> None:
        self._event_id = event_id
        self.sql_log: list[str] = []
        self.params_log: list = []
        self.closed = False

    def execute(self, sql: str, params=None) -> None:
        self.sql_log.append(sql)
        self.params_log.append(params)

    def fetchone(self) -> tuple:
        return (self._event_id,)

    def close(self) -> None:
        self.closed = True


class _TrackingConn:
    """Mock psycopg2 connection; tracks commit, rollback, and close calls."""

    def __init__(self, event_id: int = 42) -> None:
        self.autocommit = False
        self._event_id = event_id
        self.last_cursor: _InsertMockCursor | None = None
        self.commit_called = False
        self.rollback_called = False
        self.close_called = False

    def cursor(self) -> _InsertMockCursor:
        self.last_cursor = _InsertMockCursor(self._event_id)
        return self.last_cursor

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        self.close_called = True


class _NoCursorConn:
    """Connection whose cursor() raises AssertionError.

    Used to verify that validation guards fire before any database interaction.
    If a test expecting ValueError passes (i.e., AssertionError is not raised),
    it proves the guard fired before cursor() was called.
    """

    autocommit = False

    def cursor(self):
        raise AssertionError(
            "cursor() must not be called before validation completes"
        )

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# A. Event type registry
# ---------------------------------------------------------------------------

_APPROVED_EVENT_TYPES: frozenset[str] = frozenset({
    "slate_initialized",
    "schedule_retrieved",
    "game_analysis_started",
    "ecf_calculated",
    "phie_completed",
    "gse_completed",
    "mve_completed",
    "ce_completed",
    "odg_completed",
    "srl_completed",
    "candidate_created",
    "candidate_reentered",
    "evaluation_version_created",
    "recalculation_triggered",
    "lineup_observation_recorded",
    "lineup_confirmed",
    "lineup_change_detected",
    "play_id_assigned",
    "play_activated",
    "play_locked",
    "conditional_play_nominated",
    "conditional_resolved",
    "conditional_expired",
    "settlement_completed",
    "settlement_manual_required",
    "le_milestone_detected",
    "le_report_stored",
    "immutability_violation_rejected",
})


class TestEventTypeRegistry:
    def test_registry_contains_exactly_28_types(self):
        assert len(_EVENT_TYPES) == 28

    def test_registry_matches_approved_enumeration(self):
        assert _EVENT_TYPES == _APPROVED_EVENT_TYPES

    def test_registry_is_frozenset(self):
        assert isinstance(_EVENT_TYPES, frozenset)

    def test_registry_has_no_duplicates(self):
        """frozenset guarantees uniqueness; source list was also duplicate-free."""
        assert len(_EVENT_TYPES) == 28

    def test_registry_immutable_no_add_method(self):
        with pytest.raises(AttributeError):
            _EVENT_TYPES.add("new_type")  # type: ignore[attr-defined]

    def test_registry_immutable_no_discard_method(self):
        with pytest.raises(AttributeError):
            _EVENT_TYPES.discard("slate_initialized")  # type: ignore[attr-defined]

    def test_registry_immutable_no_remove_method(self):
        with pytest.raises(AttributeError):
            _EVENT_TYPES.remove("slate_initialized")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# B. Event type validation
# ---------------------------------------------------------------------------

class TestEventTypeValidation:
    @pytest.mark.parametrize("event_type", sorted(_APPROVED_EVENT_TYPES))
    def test_every_approved_type_accepted(self, event_type):
        """No ValueError raised for any of the 28 approved event types."""
        conn = _TrackingConn()
        result = record_event(conn, event_type, _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert result == 42

    def test_unknown_event_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            record_event(
                _NoCursorConn(), "invented_event_type",
                _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            )

    def test_unknown_type_rejected_before_cursor(self):
        """ValueError is raised before cursor() is called.

        _NoCursorConn.cursor() raises AssertionError. If cursor() were called
        first, this test would fail with AssertionError instead of passing.
        """
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "invented_event_type",
                _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            )

    def test_empty_string_is_unknown_event_type(self):
        with pytest.raises(ValueError):
            record_event(_NoCursorConn(), "", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)

    def test_event_type_with_trailing_whitespace_rejected(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized ",
                _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            )

    def test_event_type_uppercase_rejected(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "SLATE_INITIALIZED",
                _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            )


# ---------------------------------------------------------------------------
# C. Slate Run ID validation
# ---------------------------------------------------------------------------

class TestSlateRunIdValidation:
    def test_invalid_slate_run_id_raises_value_error(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                "ORACLE-2026-1", _VALID_TIMESTAMP,
            )

    def test_invalid_id_rejected_before_cursor(self):
        """ValueError raised before cursor() is called."""
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                "ORACLE-2026-1", _VALID_TIMESTAMP,
            )

    def test_none_slate_run_id_rejected(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                None, _VALID_TIMESTAMP,  # type: ignore[arg-type]
            )

    def test_empty_string_slate_run_id_rejected(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                "", _VALID_TIMESTAMP,
            )

    def test_malformed_date_component_rejected(self):
        """ORACLE-YYYYMMDD-NNN requires exactly 8 digit date and 3 digit suffix."""
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                "ORACLE-202607-001", _VALID_TIMESTAMP,
            )

    def test_wrong_prefix_rejected(self):
        with pytest.raises(ValueError):
            record_event(
                _NoCursorConn(), "slate_initialized",
                "ORACLE-20260725", _VALID_TIMESTAMP,
            )

    def test_event_type_validated_before_slate_run_id(self):
        """event_type check fires first: unknown type raises ValueError even with invalid slate_run_id."""
        with pytest.raises(ValueError, match="Unknown event type"):
            record_event(
                _NoCursorConn(), "bad_type", "also-bad", _VALID_TIMESTAMP,
            )


# ---------------------------------------------------------------------------
# D. Connection and cursor behaviour
# ---------------------------------------------------------------------------

class TestConnectionAndCursorBehavior:
    def test_uses_caller_provided_connection(self):
        conn = _TrackingConn(event_id=99)
        result = record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.last_cursor is not None, "cursor() was not called on the provided connection"
        assert result == 99

    def test_cursor_is_closed_after_success(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.last_cursor is not None
        assert conn.last_cursor.closed is True

    def test_cursor_is_closed_after_execute_exception(self):
        """cursor.close() must be called even when execute() raises."""
        class _ErrorCursor(_InsertMockCursor):
            def execute(self, sql: str, params=None) -> None:
                super().execute(sql, params)
                raise RuntimeError("simulated execute failure")

        class _ErrorConn(_TrackingConn):
            def cursor(self) -> _ErrorCursor:
                self.last_cursor = _ErrorCursor()
                return self.last_cursor  # type: ignore[return-value]

        conn = _ErrorConn()
        with pytest.raises(RuntimeError):
            record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.last_cursor is not None
        assert conn.last_cursor.closed is True

    def test_commit_not_called(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.commit_called is False

    def test_rollback_not_called(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.rollback_called is False

    def test_connection_not_closed(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert conn.close_called is False

    def test_autocommit_connection_rejected(self):
        """InvalidConnectionStateError raised when conn.autocommit is True."""
        conn = _TrackingConn()
        conn.autocommit = True
        with pytest.raises(InvalidConnectionStateError):
            record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)

    def test_autocommit_rejected_before_cursor(self):
        """autocommit check fires before cursor() via _require_manual_transaction."""
        conn = _NoCursorConn()
        conn.autocommit = True  # type: ignore[misc]
        with pytest.raises(InvalidConnectionStateError):
            record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)


# ---------------------------------------------------------------------------
# E. Return value
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_returns_database_assigned_event_id(self):
        conn = _TrackingConn(event_id=777)
        result = record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert result == 777

    def test_returned_value_is_int(self):
        conn = _TrackingConn(event_id=1)
        result = record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert isinstance(result, int)

    def test_returned_event_id_is_value_from_returning_clause(self):
        """event_id comes from fetchone()[0] of the RETURNING result, not computed."""
        for expected in (1, 100, 99999):
            conn = _TrackingConn(event_id=expected)
            result = record_event(
                conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP
            )
            assert result == expected


# ---------------------------------------------------------------------------
# F. Optional parameters and payload handling
# ---------------------------------------------------------------------------

class TestOptionalParameters:
    def test_game_run_id_included_in_params(self):
        conn = _TrackingConn()
        game_run_id = "ORACLE-20260725-001-BOS-NYY-746484"
        record_event(
            conn, "game_analysis_started", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            game_run_id=game_run_id,
        )
        params = conn.last_cursor.params_log[0]
        assert params[2] == game_run_id

    def test_game_run_id_none_is_sql_null(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[2] is None

    def test_play_id_included_in_params(self):
        conn = _TrackingConn()
        play_id = "EO-2026-001"
        record_event(
            conn, "play_activated", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            play_id=play_id,
        )
        params = conn.last_cursor.params_log[0]
        assert params[3] == play_id

    def test_play_id_none_is_sql_null(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[3] is None

    def test_payload_dict_serialized_as_json_string(self):
        conn = _TrackingConn()
        payload = {"confidence": 0.87, "edge_pct": 4.2}
        record_event(
            conn, "ecf_calculated", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            payload=payload,
        )
        params = conn.last_cursor.params_log[0]
        assert params[5] == json.dumps(payload)

    def test_payload_none_is_sql_null(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[5] is None

    def test_all_defaults_are_none(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[2] is None  # game_run_id
        assert params[3] is None  # play_id
        assert params[5] is None  # payload

    def test_event_type_and_slate_run_id_in_params(self):
        conn = _TrackingConn()
        record_event(conn, "schedule_retrieved", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[0] == "schedule_retrieved"
        assert params[1] == _VALID_SLATE_RUN_ID

    def test_event_timestamp_in_params(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        params = conn.last_cursor.params_log[0]
        assert params[4] == _VALID_TIMESTAMP

    def test_payload_with_nested_structure(self):
        conn = _TrackingConn()
        payload = {"model": "v3", "scores": [0.91, 0.87], "meta": {"run": 1}}
        record_event(
            conn, "ecf_calculated", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP,
            payload=payload,
        )
        params = conn.last_cursor.params_log[0]
        assert params[5] == json.dumps(payload)
        recovered = json.loads(params[5])
        assert recovered["scores"] == [0.91, 0.87]
        assert recovered["meta"]["run"] == 1


# ---------------------------------------------------------------------------
# G. SQL behaviour (static and dynamic)
# ---------------------------------------------------------------------------

class TestSqlBehavior:
    def test_sql_contains_insert(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        sql = conn.last_cursor.sql_log[0].upper()
        assert "INSERT" in sql

    def test_sql_contains_returning_event_id(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        sql = conn.last_cursor.sql_log[0]
        assert "RETURNING" in sql.upper()
        assert "event_id" in sql

    def test_sql_targets_oracle_play_events(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        sql = conn.last_cursor.sql_log[0]
        assert "oracle_play_events" in sql

    def test_executed_sql_has_no_update(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        sql = conn.last_cursor.sql_log[0].upper()
        assert "UPDATE" not in sql

    def test_executed_sql_has_no_delete(self):
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        sql = conn.last_cursor.sql_log[0].upper()
        assert "DELETE" not in sql

    def test_static_no_update_in_event_store_source(self):
        """Static verification: no UPDATE keyword in event_store.py."""
        import backend.oracle.event_store as mod
        source = inspect.getsource(mod)
        assert "UPDATE" not in source, "Unexpected UPDATE found in event_store.py source"

    def test_static_no_delete_in_event_store_source(self):
        """Static verification: no DELETE keyword in event_store.py."""
        import backend.oracle.event_store as mod
        source = inspect.getsource(mod)
        assert "DELETE" not in source, "Unexpected DELETE found in event_store.py source"

    def test_only_one_execute_call_per_record_event(self):
        """record_event() performs exactly one SQL operation."""
        conn = _TrackingConn()
        record_event(conn, "slate_initialized", _VALID_SLATE_RUN_ID, _VALID_TIMESTAMP)
        assert len(conn.last_cursor.sql_log) == 1


# ---------------------------------------------------------------------------
# G. Integration tests — require ORACLE_TEST_DATABASE_URL
# ---------------------------------------------------------------------------

_SLATE_FOR_EVENTS = "ORACLE-20260725-999"
_GAME_FOR_EVENTS = "ORACLE-20260725-999-BOS-NYY-746484"


@pytest.fixture(scope="module")
def seed_conn():
    if not _TEST_DB_URL:
        pytest.skip("ORACLE_TEST_DATABASE_URL not set")
    import psycopg2
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def seed_slate(seed_conn):
    cur = seed_conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_slate_runs
            (slate_run_id, run_date, run_status, run_started_at)
        VALUES (%s, '2026-07-25', 'initializing', NOW())
        """,
        (_SLATE_FOR_EVENTS,),
    )
    cur.close()
    yield _SLATE_FOR_EVENTS
    cur = seed_conn.cursor()
    cur.execute("TRUNCATE oracle_play_events")
    cur.execute(
        "DELETE FROM oracle_game_analyses WHERE slate_run_id = %s",
        (_SLATE_FOR_EVENTS,),
    )
    cur.execute(
        "DELETE FROM oracle_slate_runs WHERE slate_run_id = %s",
        (_SLATE_FOR_EVENTS,),
    )
    cur.close()


@pytest.fixture(scope="module")
def seed_game_analysis(seed_conn, seed_slate):
    cur = seed_conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_game_analyses
            (game_run_id, slate_run_id, external_game_id,
             home_team, away_team, first_pitch_time)
        VALUES (%s, %s, '746484', 'NYY', 'BOS', '2026-07-25T17:10:00Z')
        """,
        (_GAME_FOR_EVENTS, seed_slate),
    )
    cur.close()
    yield _GAME_FOR_EVENTS


@pytest.fixture
def txn_conn(seed_slate):
    """Per-test caller-owned connection (autocommit=False)."""
    import psycopg2
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@_requires_db
class TestEventStoreIntegration:
    def test_event_inserted_into_oracle_play_events(self, txn_conn, seed_slate):
        ts = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        event_id = record_event(txn_conn, "slate_initialized", seed_slate, ts)
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            "SELECT event_type FROM oracle_play_events WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == "slate_initialized"

    def test_returned_event_id_matches_stored_row(self, txn_conn, seed_slate):
        ts = datetime(2026, 7, 25, 12, 0, 1, tzinfo=timezone.utc)
        event_id = record_event(txn_conn, "schedule_retrieved", seed_slate, ts)
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == event_id

    def test_three_events_retrievable_in_timestamp_order(self, txn_conn, seed_slate):
        from datetime import timedelta
        base = datetime(2026, 7, 25, 13, 0, 0, tzinfo=timezone.utc)
        id1 = record_event(txn_conn, "slate_initialized", seed_slate, base)
        id2 = record_event(txn_conn, "schedule_retrieved", seed_slate, base + timedelta(seconds=1))
        id3 = record_event(txn_conn, "game_analysis_started", seed_slate, base + timedelta(seconds=2))
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            """
            SELECT event_id
            FROM oracle_play_events
            WHERE event_id = ANY(%s)
            ORDER BY event_timestamp
            """,
            ([id1, id2, id3],),
        )
        ordered_ids = [row[0] for row in cur.fetchall()]
        cur.close()
        assert ordered_ids == [id1, id2, id3]

    def test_game_run_id_round_trips(self, txn_conn, seed_slate, seed_game_analysis):
        ts = datetime(2026, 7, 25, 14, 0, 0, tzinfo=timezone.utc)
        event_id = record_event(
            txn_conn, "game_analysis_started", seed_slate, ts,
            game_run_id=seed_game_analysis,
        )
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            "SELECT game_run_id FROM oracle_play_events WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == seed_game_analysis

    def test_payload_round_trips(self, txn_conn, seed_slate):
        payload = {"confidence": 0.87, "edge_pct": 4.2, "model": "v3"}
        ts = datetime(2026, 7, 25, 14, 1, 0, tzinfo=timezone.utc)
        event_id = record_event(
            txn_conn, "ecf_calculated", seed_slate, ts,
            payload=payload,
        )
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            "SELECT event_payload FROM oracle_play_events WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == payload

    def test_payload_none_stored_as_null(self, txn_conn, seed_slate):
        ts = datetime(2026, 7, 25, 14, 2, 0, tzinfo=timezone.utc)
        event_id = record_event(txn_conn, "slate_initialized", seed_slate, ts, payload=None)
        txn_conn.commit()
        cur = txn_conn.cursor()
        cur.execute(
            "SELECT event_payload FROM oracle_play_events WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] is None

    def test_insert_allowed_by_append_only_trigger(self, txn_conn, seed_slate):
        """The WP-2 append-only trigger does not block INSERT."""
        ts = datetime(2026, 7, 25, 14, 3, 0, tzinfo=timezone.utc)
        event_id = record_event(txn_conn, "slate_initialized", seed_slate, ts)
        txn_conn.commit()
        assert isinstance(event_id, int)
        assert event_id > 0

    def test_event_store_does_not_commit_automatically(self, seed_slate):
        """Row is not visible to other connections until the caller commits."""
        import psycopg2
        conn1 = psycopg2.connect(_TEST_DB_URL)
        conn1.autocommit = False
        conn2 = psycopg2.connect(_TEST_DB_URL)
        conn2.autocommit = True
        try:
            ts = datetime(2026, 7, 25, 15, 0, 0, tzinfo=timezone.utc)
            event_id = record_event(conn1, "slate_initialized", seed_slate, ts)
            # conn1 has not committed; conn2 uses READ COMMITTED isolation
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur2.fetchone()
            cur2.close()
            assert row is None, (
                f"Row {event_id} visible before commit — "
                "Event Store must not auto-commit"
            )
            conn1.commit()
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur2.fetchone()
            cur2.close()
            assert row is not None, "Row not visible after caller commit"
            assert row[0] == event_id
        finally:
            conn1.rollback()
            conn1.close()
            conn2.close()

    def test_caller_rollback_removes_uncommitted_rows(self, seed_slate):
        """Caller rollback removes Event Store rows before they are visible."""
        import psycopg2
        conn = psycopg2.connect(_TEST_DB_URL)
        conn.autocommit = False
        try:
            ts = datetime(2026, 7, 25, 15, 1, 0, tzinfo=timezone.utc)
            event_id = record_event(conn, "schedule_retrieved", seed_slate, ts)
            # Row is visible within the same transaction
            cur = conn.cursor()
            cur.execute(
                "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
            cur.close()
            assert row is not None, "Row should be visible within the open transaction"
            conn.rollback()
            # After rollback, row must not be present in a new connection
            conn2 = psycopg2.connect(_TEST_DB_URL)
            conn2.autocommit = True
            cur2 = conn2.cursor()
            cur2.execute(
                "SELECT event_id FROM oracle_play_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur2.fetchone()
            cur2.close()
            conn2.close()
            assert row is None, "Row not removed by caller rollback"
        finally:
            conn.rollback()
            conn.close()

    def test_invalid_event_type_raises_before_any_db_write(self, txn_conn, seed_slate):
        """ValueError stops execution; no INSERT reaches the database."""
        ts = datetime(2026, 7, 25, 15, 2, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            record_event(txn_conn, "totally_invalid", seed_slate, ts)
        # No commit needed; txn_conn fixture rolls back automatically

    def test_invalid_slate_run_id_raises_before_any_db_write(self, txn_conn):
        """ValueError on invalid slate_run_id stops before any database access."""
        ts = datetime(2026, 7, 25, 15, 3, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            record_event(txn_conn, "slate_initialized", "ORACLE-BAD", ts)
