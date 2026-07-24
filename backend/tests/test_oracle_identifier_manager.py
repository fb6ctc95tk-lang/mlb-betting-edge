"""Oracle Phase 1 WP-3 — Identifier Lifecycle Manager tests.

Unit tests (Section A–G) run without a database.
PostgreSQL integration tests (Section H–N) require ORACLE_TEST_DATABASE_URL
pointing to a disposable database with Migrations 005 and 006 applied.
Integration tests are skipped when the variable is absent.

Concurrency tests (Section N) use Python threading to exercise advisory-lock
serialisation; they commit data and perform explicit cleanup within the test.
"""

from __future__ import annotations

import datetime
import os
import threading

import psycopg2
import psycopg2.errors
import pytest

from backend.oracle.identifier_manager import (
    InvalidConnectionStateError,
    InvalidIdentifierInputError,
    UnauthorizedPlayIdGenerationError,
    _LOCK_NS_PLAY,
    _LOCK_NS_SLATE,
    _create_play_id_capability,
    generate_candidate_id,
    generate_evaluation_id,
    generate_game_run_id,
    generate_play_id,
    generate_slate_run_id,
    is_valid_candidate_id,
    is_valid_evaluation_id,
    is_valid_game_run_id,
    is_valid_play_id,
    is_valid_slate_run_id,
)

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")

_requires_db = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set — WP-3 PostgreSQL integration tests skipped",
)

# ---------------------------------------------------------------------------
# Unit test helpers — minimal psycopg2 mock (no real database)
# ---------------------------------------------------------------------------

class _MockCursor:
    """Accepts advisory-lock and COUNT queries; returns a configurable count."""

    def __init__(self, count: int = 0) -> None:
        self._count = count
        self._pending_row: tuple | None = None

    def execute(self, sql: str, params=None) -> None:
        if "COUNT(*)" in sql:
            self._pending_row = (self._count,)
        else:
            self._pending_row = None

    def fetchone(self) -> tuple | None:
        return self._pending_row

    def close(self) -> None:
        pass


class _MockConn:
    """Minimal psycopg2 connection mock with autocommit=False."""

    def __init__(self, count: int = 0) -> None:
        self.autocommit = False
        self._count = count

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._count)


class _FailingConn:
    """Mock connection whose cursor() raises AssertionError — used to verify
    that certain checks fire before any database interaction."""

    autocommit = False

    def cursor(self):
        raise AssertionError(
            "cursor() was called — database was accessed before expected guard"
        )


# ---------------------------------------------------------------------------
# A. Slate Run ID — unit tests
# ---------------------------------------------------------------------------

class TestSlateRunIdUnit:
    def test_format_with_fixed_date(self):
        result = generate_slate_run_id(datetime.date(2026, 7, 20), _MockConn(count=0))
        assert result == "ORACLE-20260720-001"

    def test_uses_injected_date_not_system_clock(self):
        """A far-future date proves the system clock is never consulted."""
        result = generate_slate_run_id(datetime.date(2099, 1, 1), _MockConn(count=0))
        assert result == "ORACLE-20990101-001"

    def test_sequence_starts_at_001_when_zero_existing(self):
        result = generate_slate_run_id(datetime.date(2026, 7, 20), _MockConn(count=0))
        assert result.endswith("-001")

    def test_sequence_increments_to_002_when_one_existing(self):
        result = generate_slate_run_id(datetime.date(2026, 7, 20), _MockConn(count=1))
        assert result.endswith("-002")

    def test_three_digit_zero_padded_suffix(self):
        result = generate_slate_run_id(datetime.date(2026, 7, 20), _MockConn(count=9))
        assert result.endswith("-010")

    def test_rejects_non_date_input(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_slate_run_id("2026-07-20", _MockConn())

    def test_rejects_autocommit_connection(self):
        conn = _MockConn()
        conn.autocommit = True
        with pytest.raises(InvalidConnectionStateError):
            generate_slate_run_id(datetime.date(2026, 7, 20), conn)


# ---------------------------------------------------------------------------
# B. Game Analysis Run ID — unit tests
# ---------------------------------------------------------------------------

class TestGameRunIdUnit:
    _SLATE = "ORACLE-20260720-001"

    def test_known_output(self):
        result = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        assert result == "ORACLE-20260720-001-BOS-NYY-745001"

    def test_deterministic(self):
        a = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        b = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        assert a == b

    def test_away_team_appears_before_home_team(self):
        result = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        away_pos = result.index("BOS")
        home_pos = result.index("NYY")
        assert away_pos < home_pos

    def test_game_pk_included_in_output(self):
        result = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        assert "745001" in result

    def test_doubleheader_games_produce_distinct_ids(self):
        game1 = generate_game_run_id(self._SLATE, "BOS", "NYY", 745001)
        game2 = generate_game_run_id(self._SLATE, "BOS", "NYY", 745002)
        assert game1 != game2

    def test_rejects_invalid_away_team_lowercase(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "bos", "NYY", 745001)

    def test_rejects_invalid_away_team_too_long(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOST", "NYY", 745001)

    def test_rejects_invalid_home_team_empty(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "", 745001)

    def test_rejects_invalid_home_team_with_digits(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "NY1", 745001)

    def test_rejects_game_pk_zero(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "NYY", 0)

    def test_rejects_game_pk_negative(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "NYY", -1)

    def test_rejects_game_pk_string(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "NYY", "745001")

    def test_rejects_game_pk_bool(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id(self._SLATE, "BOS", "NYY", True)

    def test_rejects_malformed_slate_run_id(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_game_run_id("ORACLE-2026-001", "BOS", "NYY", 745001)

    def test_two_char_team_abbreviation_accepted(self):
        """Teams with 2-letter abbreviations (e.g. SD) are valid."""
        result = generate_game_run_id(self._SLATE, "SD", "LA", 745001)
        assert "SD" in result
        assert "LA" in result


# ---------------------------------------------------------------------------
# C. Evaluation ID — unit tests
# ---------------------------------------------------------------------------

class TestEvaluationIdUnit:
    _GAME = "ORACLE-20260720-001-BOS-NYY-745001"

    def test_known_output(self):
        result = generate_evaluation_id(self._GAME, "ML", 1)
        assert result == "EVAL-ORACLE-20260720-001-BOS-NYY-745001-ML-v1"

    def test_version_increment(self):
        v1 = generate_evaluation_id(self._GAME, "ML", 1)
        v2 = generate_evaluation_id(self._GAME, "ML", 2)
        assert v1.endswith("-v1")
        assert v2.endswith("-v2")
        assert v1 != v2

    def test_version_zero_rejected(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_evaluation_id(self._GAME, "ML", 0)

    def test_version_negative_rejected(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_evaluation_id(self._GAME, "ML", -1)

    def test_version_bool_rejected(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_evaluation_id(self._GAME, "ML", True)

    def test_unsupported_market_rejected(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_evaluation_id(self._GAME, "NRFI", 1)

    def test_ml_only_enforcement(self):
        """Only 'ML' is accepted; any other string is rejected."""
        for bad in ("ml", "F5ML", "FGT", "", "MONEYLINE"):
            with pytest.raises(InvalidIdentifierInputError):
                generate_evaluation_id(self._GAME, bad, 1)

    def test_rejects_malformed_game_run_id(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_evaluation_id("ORACLE-20260720-001-BOS-NYY", "ML", 1)


# ---------------------------------------------------------------------------
# D. Candidate ID — unit tests
# ---------------------------------------------------------------------------

class TestCandidateIdUnit:
    _GAME = "ORACLE-20260720-001-BOS-NYY-745001"

    def test_known_output(self):
        result = generate_candidate_id(self._GAME, "ML")
        assert result == "CAND-ORACLE-20260720-001-BOS-NYY-745001-ML"

    def test_deterministic(self):
        a = generate_candidate_id(self._GAME, "ML")
        b = generate_candidate_id(self._GAME, "ML")
        assert a == b

    def test_ml_only_enforcement(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_candidate_id(self._GAME, "F5ML")

    def test_unsupported_market_rejected(self):
        for bad in ("ml", "NRFI", "FGT", "", "TOTALS"):
            with pytest.raises(InvalidIdentifierInputError):
                generate_candidate_id(self._GAME, bad)

    def test_rejects_malformed_game_run_id(self):
        with pytest.raises(InvalidIdentifierInputError):
            generate_candidate_id("NOT-A-GAME-ID", "ML")


# ---------------------------------------------------------------------------
# E. Play ID — unit tests
# ---------------------------------------------------------------------------

class TestPlayIdUnit:
    def test_format_with_fixed_date(self):
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2026, 7, 20), _MockConn(count=0), cap)
        assert result == "EO-2026-001"

    def test_year_boundary_december_31_uses_correct_year(self):
        """Play ID year comes from current_date_et.year, not system clock."""
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2026, 12, 31), _MockConn(count=0), cap)
        assert result.startswith("EO-2026-")

    def test_year_boundary_january_1_uses_new_year(self):
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2027, 1, 1), _MockConn(count=0), cap)
        assert result.startswith("EO-2027-")

    def test_far_future_date_uses_injected_year(self):
        """A 2099 date proves the system clock is never consulted."""
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2099, 12, 31), _MockConn(count=0), cap)
        assert result.startswith("EO-2099-")

    def test_sequence_starts_at_001(self):
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2026, 7, 20), _MockConn(count=0), cap)
        assert result.endswith("-001")

    def test_sequence_increments(self):
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2026, 7, 20), _MockConn(count=1), cap)
        assert result.endswith("-002")

    def test_governed_path_succeeds_with_valid_capability(self):
        cap = _create_play_id_capability()
        result = generate_play_id(datetime.date(2026, 7, 20), _MockConn(count=0), cap)
        assert result == "EO-2026-001"

    def test_unauthorized_rejection_before_db_access(self):
        """UnauthorizedPlayIdGenerationError is raised before cursor() is called."""
        with pytest.raises(UnauthorizedPlayIdGenerationError):
            generate_play_id(
                datetime.date(2026, 7, 20),
                _FailingConn(),
                capability="not-a-capability",
            )

    def test_unauthorized_rejection_with_none_capability(self):
        with pytest.raises(UnauthorizedPlayIdGenerationError):
            generate_play_id(datetime.date(2026, 7, 20), _FailingConn(), None)

    def test_unauthorized_rejection_with_bool_capability(self):
        with pytest.raises(UnauthorizedPlayIdGenerationError):
            generate_play_id(datetime.date(2026, 7, 20), _FailingConn(), True)

    def test_rejects_autocommit_connection(self):
        conn = _MockConn()
        conn.autocommit = True
        cap = _create_play_id_capability()
        with pytest.raises(InvalidConnectionStateError):
            generate_play_id(datetime.date(2026, 7, 20), conn, cap)

    def test_rejects_non_date_input(self):
        cap = _create_play_id_capability()
        with pytest.raises(InvalidIdentifierInputError):
            generate_play_id("2026-07-20", _MockConn(), cap)


# ---------------------------------------------------------------------------
# F. Validation functions — unit tests
# ---------------------------------------------------------------------------

class TestValidationFunctions:

    # Slate Run ID

    def test_valid_slate_run_id(self):
        assert is_valid_slate_run_id("ORACLE-20260720-001") is True

    def test_slate_run_id_false_empty(self):
        assert is_valid_slate_run_id("") is False

    def test_slate_run_id_false_lowercase(self):
        assert is_valid_slate_run_id("oracle-20260720-001") is False

    def test_slate_run_id_false_sequence_too_short(self):
        assert is_valid_slate_run_id("ORACLE-20260720-01") is False

    def test_slate_run_id_false_sequence_too_long(self):
        assert is_valid_slate_run_id("ORACLE-20260720-0001") is False

    def test_slate_run_id_false_date_too_short(self):
        assert is_valid_slate_run_id("ORACLE-202607-001") is False

    def test_slate_run_id_false_wrong_prefix(self):
        assert is_valid_slate_run_id("ORACL-20260720-001") is False

    def test_slate_run_id_false_non_string(self):
        assert is_valid_slate_run_id(None) is False
        assert is_valid_slate_run_id(12345) is False

    # Game Analysis Run ID

    def test_valid_game_run_id(self):
        assert is_valid_game_run_id("ORACLE-20260720-001-BOS-NYY-745001") is True

    def test_valid_game_run_id_two_char_teams(self):
        assert is_valid_game_run_id("ORACLE-20260720-001-SD-LA-745001") is True

    def test_game_run_id_false_missing_game_pk(self):
        assert is_valid_game_run_id("ORACLE-20260720-001-BOS-NYY") is False

    def test_game_run_id_false_lowercase_teams(self):
        assert is_valid_game_run_id("ORACLE-20260720-001-bos-NYY-745001") is False

    def test_game_run_id_false_empty(self):
        assert is_valid_game_run_id("") is False

    def test_game_run_id_false_bad_sequence(self):
        assert is_valid_game_run_id("ORACLE-20260720-01-BOS-NYY-745001") is False

    def test_game_run_id_false_non_string(self):
        assert is_valid_game_run_id(None) is False

    # Evaluation ID

    def test_valid_evaluation_id(self):
        assert is_valid_evaluation_id(
            "EVAL-ORACLE-20260720-001-BOS-NYY-745001-ML-v1"
        ) is True

    def test_evaluation_id_false_unsupported_market(self):
        assert is_valid_evaluation_id(
            "EVAL-ORACLE-20260720-001-BOS-NYY-745001-NRFI-v1"
        ) is False

    def test_evaluation_id_false_missing_version(self):
        assert is_valid_evaluation_id(
            "EVAL-ORACLE-20260720-001-BOS-NYY-745001-ML"
        ) is False

    def test_evaluation_id_false_lowercase(self):
        assert is_valid_evaluation_id(
            "eval-ORACLE-20260720-001-BOS-NYY-745001-ML-v1"
        ) is False

    def test_evaluation_id_false_empty(self):
        assert is_valid_evaluation_id("") is False

    def test_evaluation_id_false_non_string(self):
        assert is_valid_evaluation_id(None) is False

    # Candidate ID

    def test_valid_candidate_id(self):
        assert is_valid_candidate_id(
            "CAND-ORACLE-20260720-001-BOS-NYY-745001-ML"
        ) is True

    def test_candidate_id_false_unsupported_market(self):
        assert is_valid_candidate_id(
            "CAND-ORACLE-20260720-001-BOS-NYY-745001-NRFI"
        ) is False

    def test_candidate_id_false_has_version_suffix(self):
        assert is_valid_candidate_id(
            "CAND-ORACLE-20260720-001-BOS-NYY-745001-ML-v1"
        ) is False

    def test_candidate_id_false_lowercase(self):
        assert is_valid_candidate_id(
            "cand-ORACLE-20260720-001-BOS-NYY-745001-ML"
        ) is False

    def test_candidate_id_false_empty(self):
        assert is_valid_candidate_id("") is False

    def test_candidate_id_false_non_string(self):
        assert is_valid_candidate_id(None) is False

    # Play ID

    def test_valid_play_id(self):
        assert is_valid_play_id("EO-2026-001") is True

    def test_play_id_false_empty(self):
        assert is_valid_play_id("") is False

    def test_play_id_false_sequence_too_short(self):
        assert is_valid_play_id("EO-2026-01") is False

    def test_play_id_false_sequence_too_long(self):
        assert is_valid_play_id("EO-2026-0001") is False

    def test_play_id_false_year_too_short(self):
        assert is_valid_play_id("EO-26-001") is False

    def test_play_id_false_lowercase(self):
        assert is_valid_play_id("eo-2026-001") is False

    def test_play_id_false_wrong_prefix(self):
        assert is_valid_play_id("EP-2026-001") is False

    def test_play_id_false_non_string(self):
        assert is_valid_play_id(None) is False
        assert is_valid_play_id(2026001) is False


# ---------------------------------------------------------------------------
# G. Lock key derivation — unit tests (no database)
# ---------------------------------------------------------------------------

class TestLockKeyDerivation:
    def test_slate_run_lock_keys_differ_by_date(self):
        from backend.oracle.identifier_manager import _slate_run_lock_key
        k1 = _slate_run_lock_key(20260720)
        k2 = _slate_run_lock_key(20260721)
        assert k1 != k2

    def test_play_id_lock_keys_differ_by_year(self):
        from backend.oracle.identifier_manager import _play_id_lock_key
        k1 = _play_id_lock_key(2026)
        k2 = _play_id_lock_key(2027)
        assert k1 != k2

    def test_slate_and_play_namespaces_do_not_alias(self):
        from backend.oracle.identifier_manager import (
            _play_id_lock_key,
            _slate_run_lock_key,
        )
        # Construct a date whose low-32 bits match a year value that Play ID uses.
        # Both keys must differ because they have different namespace constants.
        slate_key = _slate_run_lock_key(2026)   # date_int coincidentally equals a year
        play_key = _play_id_lock_key(2026)
        assert slate_key != play_key

    def test_lock_keys_fit_in_postgresql_bigint(self):
        from backend.oracle.identifier_manager import (
            _play_id_lock_key,
            _slate_run_lock_key,
        )
        _PG_BIGINT_MAX = (2 ** 63) - 1
        assert _slate_run_lock_key(99991231) <= _PG_BIGINT_MAX
        assert _play_id_lock_key(9999) <= _PG_BIGINT_MAX

    def test_lock_keys_are_deterministic(self):
        from backend.oracle.identifier_manager import _slate_run_lock_key
        assert _slate_run_lock_key(20260720) == _slate_run_lock_key(20260720)


# ===========================================================================
# PostgreSQL integration tests — require ORACLE_TEST_DATABASE_URL
# ===========================================================================

# Shared test dates chosen to avoid conflict with WP-1/WP-2 test data.
# All integration tests use dates in year 2099 or beyond.
_DATE_SLATE_ZERO = datetime.date(2099, 1, 1)   # zero-existing sequence test
_DATE_SLATE_ONE = datetime.date(2099, 1, 2)    # one-existing sequence test
_DATE_NO_COMMIT = datetime.date(2099, 1, 4)    # no-internal-commit test
_DATE_NO_ROLLBACK = datetime.date(2099, 1, 5)  # no-internal-rollback test
_DATE_TXN_ACTIVE = datetime.date(2099, 1, 6)   # caller-transaction-remains-active test
_DATE_LOCK_CHECK = datetime.date(2099, 1, 7)   # advisory-lock existence test
_DATE_LOCK_RELEASE = datetime.date(2099, 1, 8) # rollback-releases-lock test
_DATE_NO_WRITE = datetime.date(2099, 1, 9)     # generator-writes-no-records test
_DATE_CONCURRENT_SLATE = datetime.date(2099, 1, 10)  # concurrent slate test (commits)
_YEAR_PLAY_ZERO = datetime.date(2099, 3, 1)    # play id zero-existing
_YEAR_PLAY_ONE = datetime.date(2099, 3, 2)     # play id one-existing (different day, same year)
_YEAR_PLAY_BOUNDARY = datetime.date(2098, 6, 1) # calendar-year reset (year 2098)
_DATE_CONCURRENT_PLAY = datetime.date(2099, 2, 1)   # concurrent play test (commits)


@pytest.fixture(scope="function")
def txn_conn():
    """psycopg2 connection with autocommit=False; rolls back after each test."""
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    yield conn
    try:
        conn.rollback()
    except Exception:
        pass
    conn.close()


@pytest.fixture(scope="function")
def auto_conn():
    """psycopg2 connection with autocommit=True for setup/teardown helpers."""
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = True
    yield conn
    conn.close()


def _insert_slate(cur, slate_id: str, run_date: datetime.date) -> None:
    cur.execute(
        """INSERT INTO oracle_slate_runs
               (slate_run_id, run_date, run_status, run_started_at)
           VALUES (%s, %s, 'initializing', NOW())""",
        (slate_id, run_date),
    )


def _insert_game(cur, game_id: str, slate_id: str) -> None:
    cur.execute(
        """INSERT INTO oracle_game_analyses
               (game_run_id, slate_run_id, external_game_id,
                home_team, away_team, first_pitch_time)
           VALUES (%s, %s, '999999', 'NYY', 'BOS', NOW())""",
        (game_id, slate_id),
    )


def _insert_play(
    cur,
    play_id: str,
    slate_id: str,
    game_id: str,
    candidate_id: str,
) -> None:
    cur.execute(
        """INSERT INTO oracle_plays
               (play_id, candidate_id, slate_run_id, game_run_id,
                market, selected_side, odds_at_nomination, nomination_timestamp)
           VALUES (%s, %s, %s, %s, 'ML', 'BOS', -110, NOW())""",
        (play_id, candidate_id, slate_id, game_id),
    )


# ---------------------------------------------------------------------------
# H. Slate Run ID sequence — integration tests
# ---------------------------------------------------------------------------

@_requires_db
class TestSlateRunIdIntegration:

    def test_zero_existing_produces_001(self, txn_conn):
        result = generate_slate_run_id(_DATE_SLATE_ZERO, txn_conn)
        assert result == f"ORACLE-20990101-001"

    def test_one_existing_produces_002(self, txn_conn):
        cur = txn_conn.cursor()
        _insert_slate(cur, "ORACLE-20990102-001", _DATE_SLATE_ONE)
        cur.close()
        result = generate_slate_run_id(_DATE_SLATE_ONE, txn_conn)
        assert result == "ORACLE-20990102-002"

    def test_generator_writes_no_records(self, txn_conn):
        cur = txn_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_slate_runs WHERE run_date = %s",
                    (_DATE_NO_WRITE,))
        count_before = cur.fetchone()[0]
        cur.close()

        generate_slate_run_id(_DATE_NO_WRITE, txn_conn)

        cur = txn_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_slate_runs WHERE run_date = %s",
                    (_DATE_NO_WRITE,))
        count_after = cur.fetchone()[0]
        cur.close()
        assert count_after == count_before

    def test_autocommit_misuse_fails_clearly(self):
        conn = psycopg2.connect(_TEST_DB_URL)
        conn.autocommit = True
        try:
            with pytest.raises(InvalidConnectionStateError):
                generate_slate_run_id(_DATE_SLATE_ZERO, conn)
        finally:
            conn.close()

    def test_no_internal_commit(self, txn_conn):
        """generate_slate_run_id must not commit the caller's transaction."""
        sentinel_id = "ORACLE-20990104-SENTINEL"
        cur = txn_conn.cursor()
        _insert_slate(cur, sentinel_id, _DATE_NO_COMMIT)
        cur.close()

        generate_slate_run_id(_DATE_NO_COMMIT, txn_conn)

        # A separate committed connection must NOT see the sentinel (not yet committed).
        verify = psycopg2.connect(_TEST_DB_URL)
        verify.autocommit = True
        cur2 = verify.cursor()
        cur2.execute(
            "SELECT 1 FROM oracle_slate_runs WHERE slate_run_id = %s",
            (sentinel_id,),
        )
        row = cur2.fetchone()
        cur2.close()
        verify.close()
        assert row is None, "generate_slate_run_id committed the caller's transaction"

    def test_no_internal_rollback(self, txn_conn):
        """generate_slate_run_id must not roll back the caller's transaction."""
        sentinel_id = "ORACLE-20990105-SENTINEL"
        cur = txn_conn.cursor()
        _insert_slate(cur, sentinel_id, _DATE_NO_ROLLBACK)
        cur.close()

        generate_slate_run_id(_DATE_NO_ROLLBACK, txn_conn)

        # The sentinel must still be visible within the same transaction.
        cur2 = txn_conn.cursor()
        cur2.execute(
            "SELECT 1 FROM oracle_slate_runs WHERE slate_run_id = %s",
            (sentinel_id,),
        )
        row = cur2.fetchone()
        cur2.close()
        assert row is not None, "generate_slate_run_id rolled back the caller's transaction"

    def test_caller_transaction_remains_active(self):
        """After generate_slate_run_id returns the caller can still commit work."""
        conn = psycopg2.connect(_TEST_DB_URL)
        conn.autocommit = False
        sentinel_id = "ORACLE-20990106-SENTINEL"
        generated_id = None
        try:
            cur = conn.cursor()
            _insert_slate(cur, sentinel_id, _DATE_TXN_ACTIVE)
            cur.close()

            generated_id = generate_slate_run_id(_DATE_TXN_ACTIVE, conn)

            cur = conn.cursor()
            _insert_slate(cur, generated_id, _DATE_TXN_ACTIVE)
            cur.close()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        # Verify both rows were committed.
        verify = psycopg2.connect(_TEST_DB_URL)
        verify.autocommit = True
        cur = verify.cursor()
        cur.execute(
            "SELECT slate_run_id FROM oracle_slate_runs WHERE run_date = %s",
            (_DATE_TXN_ACTIVE,),
        )
        ids = {row[0] for row in cur.fetchall()}
        cur.close()
        verify.close()

        assert sentinel_id in ids
        assert generated_id in ids

        # Cleanup committed rows.
        cleanup = psycopg2.connect(_TEST_DB_URL)
        cleanup.autocommit = True
        cur = cleanup.cursor()
        cur.execute("DELETE FROM oracle_slate_runs WHERE run_date = %s", (_DATE_TXN_ACTIVE,))
        cur.close()
        cleanup.close()

    def test_advisory_lock_held_within_transaction(self, txn_conn):
        """After generate_slate_run_id the advisory lock appears in pg_locks."""
        generate_slate_run_id(_DATE_LOCK_CHECK, txn_conn)
        cur = txn_conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM pg_locks
               WHERE locktype = 'advisory'
                 AND pid = pg_backend_pid()
                 AND granted""",
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count >= 1, "No granted advisory lock found after generate_slate_run_id"

    def test_rollback_releases_transaction_scoped_lock(self):
        """Transaction rollback releases the advisory lock so another connection can acquire it."""
        conn1 = psycopg2.connect(_TEST_DB_URL)
        conn1.autocommit = False
        generate_slate_run_id(_DATE_LOCK_RELEASE, conn1)
        conn1.rollback()
        conn1.close()

        # The lock must now be available for conn2 without blocking.
        conn2 = psycopg2.connect(_TEST_DB_URL)
        conn2.autocommit = False
        try:
            result = generate_slate_run_id(_DATE_LOCK_RELEASE, conn2)
            assert result == f"ORACLE-20990108-001"
        finally:
            conn2.rollback()
            conn2.close()


# ---------------------------------------------------------------------------
# I. Play ID sequence — integration tests
# ---------------------------------------------------------------------------

@_requires_db
class TestPlayIdIntegration:
    """Integration tests for Play ID generation using real PostgreSQL.

    Helper slate/game rows are inserted within each transaction and rolled
    back on teardown. Year 2099 is used for all sequence tests; year 2098 is
    used for the calendar-year reset test.
    """

    _SLATE_PLAY = "ORACLE-20990301-WP3PLAY"
    _GAME_PLAY = "ORACLE-20990301-WP3PLAY-BOS-NYY-999001"

    def _ensure_prerequisites(self, cur) -> None:
        """Insert the supporting slate and game rows if they don't already exist."""
        cur.execute(
            "SELECT 1 FROM oracle_slate_runs WHERE slate_run_id = %s",
            (self._SLATE_PLAY,),
        )
        if cur.fetchone() is None:
            _insert_slate(cur, self._SLATE_PLAY, _YEAR_PLAY_ZERO)
        cur.execute(
            "SELECT 1 FROM oracle_game_analyses WHERE game_run_id = %s",
            (self._GAME_PLAY,),
        )
        if cur.fetchone() is None:
            _insert_game(cur, self._GAME_PLAY, self._SLATE_PLAY)

    def test_zero_existing_produces_001(self, txn_conn):
        cur = txn_conn.cursor()
        self._ensure_prerequisites(cur)
        cur.close()
        cap = _create_play_id_capability()
        result = generate_play_id(_YEAR_PLAY_ZERO, txn_conn, cap)
        assert result == "EO-2099-001"

    def test_one_existing_produces_002(self, txn_conn):
        cur = txn_conn.cursor()
        self._ensure_prerequisites(cur)
        _insert_play(
            cur,
            "EO-2099-001",
            self._SLATE_PLAY,
            self._GAME_PLAY,
            f"CAND-{self._GAME_PLAY}-ML",
        )
        cur.close()
        cap = _create_play_id_capability()
        result = generate_play_id(_YEAR_PLAY_ZERO, txn_conn, cap)
        assert result == "EO-2099-002"

    def test_calendar_year_reset_produces_001(self, txn_conn):
        """A Play ID for year 2098 is not counted when generating for year 2099."""
        # Setup: slate and game for year 2098 prerequisites
        slate_98 = "ORACLE-20980601-WP3PLAY98"
        game_98 = "ORACLE-20980601-WP3PLAY98-BOS-NYY-998001"
        cur = txn_conn.cursor()
        _insert_slate(cur, slate_98, _YEAR_PLAY_BOUNDARY)
        _insert_game(cur, game_98, slate_98)
        _insert_play(
            cur,
            "EO-2098-001",
            slate_98,
            game_98,
            f"CAND-{game_98}-ML",
        )
        cur.close()

        # Generating for 2099 must count only 2099 plays (zero), producing 001.
        cap = _create_play_id_capability()
        result = generate_play_id(_YEAR_PLAY_ZERO, txn_conn, cap)
        assert result == "EO-2099-001"

    def test_autocommit_misuse_fails_clearly(self):
        conn = psycopg2.connect(_TEST_DB_URL)
        conn.autocommit = True
        cap = _create_play_id_capability()
        try:
            with pytest.raises(InvalidConnectionStateError):
                generate_play_id(_YEAR_PLAY_ZERO, conn, cap)
        finally:
            conn.close()

    def test_unauthorized_invocation_before_db_access(self):
        """Unauthorized invocation raises before any cursor is created."""
        with pytest.raises(UnauthorizedPlayIdGenerationError):
            generate_play_id(_YEAR_PLAY_ZERO, _FailingConn(), "not-a-capability")

    def test_no_internal_commit(self, txn_conn):
        """generate_play_id must not commit the caller's transaction."""
        _SLATE_NC = "ORACLE-20990301-PLAYNC"
        _GAME_NC = "ORACLE-20990301-PLAYNC-BOS-NYY-999002"
        cur = txn_conn.cursor()
        _insert_slate(cur, _SLATE_NC, _YEAR_PLAY_ZERO)
        _insert_game(cur, _GAME_NC, _SLATE_NC)
        cur.close()

        cap = _create_play_id_capability()
        generate_play_id(_YEAR_PLAY_ZERO, txn_conn, cap)

        # Must not be visible from another committed connection.
        verify = psycopg2.connect(_TEST_DB_URL)
        verify.autocommit = True
        cur2 = verify.cursor()
        cur2.execute(
            "SELECT 1 FROM oracle_slate_runs WHERE slate_run_id = %s", (_SLATE_NC,)
        )
        row = cur2.fetchone()
        cur2.close()
        verify.close()
        assert row is None, "generate_play_id committed the caller's transaction"

    def test_generator_writes_no_records(self, txn_conn):
        cur = txn_conn.cursor()
        self._ensure_prerequisites(cur)
        cur.execute("SELECT COUNT(*) FROM oracle_plays WHERE play_id LIKE 'EO-2099-%'")
        count_before = cur.fetchone()[0]
        cur.close()

        cap = _create_play_id_capability()
        generate_play_id(_YEAR_PLAY_ZERO, txn_conn, cap)

        cur = txn_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_plays WHERE play_id LIKE 'EO-2099-%'")
        count_after = cur.fetchone()[0]
        cur.close()
        assert count_after == count_before


# ---------------------------------------------------------------------------
# N. Concurrency tests — these tests commit data and perform explicit cleanup
# ---------------------------------------------------------------------------

@_requires_db
class TestConcurrency:

    def test_concurrent_slate_run_ids_are_distinct(self):
        """Two concurrent threads generating Slate Run IDs on the same date
        produce distinct, sequentially correct IDs."""
        test_date = _DATE_CONCURRENT_SLATE
        results: list[str] = []
        errors: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker() -> None:
            conn = psycopg2.connect(_TEST_DB_URL)
            conn.autocommit = False
            try:
                barrier.wait()
                slate_id = generate_slate_run_id(test_date, conn)
                cur = conn.cursor()
                _insert_slate(cur, slate_id, test_date)
                cur.close()
                conn.commit()
                results.append(slate_id)
            except Exception as exc:
                errors.append(str(exc))
                conn.rollback()
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        cleanup = psycopg2.connect(_TEST_DB_URL)
        cleanup.autocommit = True
        cur = cleanup.cursor()
        cur.execute("DELETE FROM oracle_slate_runs WHERE run_date = %s", (test_date,))
        cur.close()
        cleanup.close()

        assert not errors, f"Worker errors: {errors}"
        assert len(results) == 2
        assert len(set(results)) == 2, f"Duplicate Slate Run IDs: {results}"
        assert set(results) == {"ORACLE-20990110-001", "ORACLE-20990110-002"}

    def test_concurrent_play_ids_are_distinct(self):
        """Two concurrent threads generating Play IDs in the same calendar year
        produce distinct, sequentially correct IDs."""
        test_date = _DATE_CONCURRENT_PLAY   # year 2099
        # Pre-create shared prerequisite rows (committed before concurrent phase).
        slate_id = "ORACLE-20990201-CONC"
        game_id = "ORACLE-20990201-CONC-BOS-NYY-777001"

        setup = psycopg2.connect(_TEST_DB_URL)
        setup.autocommit = True
        cur = setup.cursor()
        _insert_slate(cur, slate_id, test_date)
        _insert_game(cur, game_id, slate_id)
        cur.close()
        setup.close()

        results: list[str] = []
        errors: list[str] = []
        barrier = threading.Barrier(2, timeout=10)

        def worker() -> None:
            conn = psycopg2.connect(_TEST_DB_URL)
            conn.autocommit = False
            cap = _create_play_id_capability()
            try:
                barrier.wait()
                play_id = generate_play_id(test_date, conn, cap)
                cur = conn.cursor()
                _insert_play(
                    cur,
                    play_id,
                    slate_id,
                    game_id,
                    f"CAND-{game_id}-ML-{play_id}",
                )
                cur.close()
                conn.commit()
                results.append(play_id)
            except Exception as exc:
                errors.append(str(exc))
                conn.rollback()
            finally:
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        cleanup = psycopg2.connect(_TEST_DB_URL)
        cleanup.autocommit = True
        cur = cleanup.cursor()
        cur.execute("DELETE FROM oracle_plays WHERE slate_run_id = %s", (slate_id,))
        cur.execute("DELETE FROM oracle_game_analyses WHERE slate_run_id = %s", (slate_id,))
        cur.execute("DELETE FROM oracle_slate_runs WHERE slate_run_id = %s", (slate_id,))
        cur.close()
        cleanup.close()

        assert not errors, f"Worker errors: {errors}"
        assert len(results) == 2
        assert len(set(results)) == 2, f"Duplicate Play IDs: {results}"
        assert set(results) == {"EO-2099-001", "EO-2099-002"}

    def test_disposable_cleanup_verified(self, auto_conn):
        """Verify that concurrency test cleanup leaves no 2099 orphan rows."""
        cur = auto_conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM oracle_plays WHERE play_id LIKE 'EO-2099-%'"
        )
        play_count = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM oracle_game_analyses "
            "WHERE game_run_id LIKE 'ORACLE-2099%-CONC%'"
        )
        game_count = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM oracle_slate_runs "
            "WHERE slate_run_id LIKE 'ORACLE-2099%-CONC%'"
        )
        slate_count = cur.fetchone()[0]

        cur.close()

        assert play_count == 0, f"{play_count} orphan EO-2099 play rows found"
        assert game_count == 0, f"{game_count} orphan CONC game rows found"
        assert slate_count == 0, f"{slate_count} orphan CONC slate rows found"
