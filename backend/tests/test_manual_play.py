"""Acceptance tests for MANUAL paper-play recording (PM-1139; validation completed under PM-1141).

Connection enforcement is installed at import — BEFORE importing the code under test or attempting
any connection. Tests may reach a database ONLY at 127.0.0.1:5432/oracle_manual_play_test; the
maintenance `postgres` db is permitted ONLY during the bounded create/drop windows. Every destination
is validated and REJECTED BEFORE any connection is opened, with credential-stripped attempt evidence.

The real disposable-DB lifecycle (absent -> create -> provision-through-014 -> test -> drop -> absent)
runs ONLY when an explicitly approved loopback DSN is provided in ORACLE_MANUAL_PLAY_TEST_DSN. Credential
discovery, fallback, and disclosure are prohibited: when the DSN is absent the lifecycle skips and no
connection is attempted. Pure-logic, mock-connection, and connection-gate negatives run without any DB.
"""

from __future__ import annotations

import os
import pathlib
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import pytest

# --- Connection-enforcement harness (installed before importing code under test) ---

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_TEST_DBNAME = "oracle_manual_play_test"
_MAINT_DBNAME = "postgres"
_ALLOWED = {
    "maintenance": {"port": 5432, "dbnames": frozenset({_MAINT_DBNAME})},
    "test": {"port": 5432, "dbnames": frozenset({_TEST_DBNAME})},
}
_phase = {"current": None}
_attempts: list[dict] = []


class ConnectionRejected(Exception):
    """Raised (before any connection) when a destination is not allowed in the phase."""


def set_phase(phase):
    _phase["current"] = phase


def parse_destination(dsn=None, **kw):
    if dsn:
        u = urlsplit(dsn)
        return (u.hostname, u.port or 5432, (u.path or "/").lstrip("/"))
    return (kw.get("host"), kw.get("port", 5432), kw.get("dbname"))


def sanitize(dsn=None, **kw):
    if dsn:
        u = urlsplit(dsn)
        user = (u.username + ":***@") if u.username else ""
        return f"{u.scheme}://{user}{u.hostname or ''}:{u.port or 5432}/{(u.path or '/').lstrip('/')}"
    return f"host={kw.get('host')} port={kw.get('port', 5432)} dbname={kw.get('dbname')} password=***"


def evaluate_destination(phase, host, port, dbname):
    if phase not in _ALLOWED:
        return (False, f"phase {phase!r} denies all connections")
    if host not in _LOOPBACK_HOSTS:
        return (False, f"host {host!r} is not loopback")
    rule = _ALLOWED[phase]
    if port != rule["port"]:
        return (False, f"port {port!r} not allowed")
    if dbname not in rule["dbnames"]:
        return (False, f"dbname {dbname!r} not allowed in phase {phase!r}")
    return (True, "allowed")


def guarded_connect(_real_connect, dsn=None, **kw):
    host, port, dbname = parse_destination(dsn, **kw)
    allowed, reason = evaluate_destination(_phase["current"], host, port, dbname)
    _attempts.append({"phase": _phase["current"], "dest": sanitize(dsn, **kw),
                      "allowed": allowed, "reason": reason})
    if not allowed:
        raise ConnectionRejected(reason)  # rejected BEFORE any real connection
    return _real_connect(dsn, **kw) if dsn else _real_connect(**kw)


try:  # pragma: no cover - environment dependent
    import psycopg2 as _pg
    _REAL_CONNECT = _pg.connect

    def _wrapped(dsn=None, **kw):
        return guarded_connect(_REAL_CONNECT, dsn, **kw)

    _pg.connect = _wrapped
except Exception:  # psycopg2 absent — pure/mock tests still run
    _pg = None

from backend.oracle import identifier_manager as im  # noqa: E402
from backend.oracle import manual_play as mp  # noqa: E402
from backend.oracle.manual_play import (  # noqa: E402
    CHANGED_INPUT,
    CONTEXT_TEST_FIXTURE,
    EXACT_REPLAY,
    KillSwitchHaltError,
    ManualPlayMembershipError,
    ManualPlayValidationError,
    ORIGIN_MANUAL,
    RECORDED,
    build_manual_candidate_id,
    is_valid_american_odds,
    normalize_market,
    normalize_side,
    normalize_stake,
    record_manual_play,
)

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "1"}
_TS = datetime(2026, 7, 25, 20, 45, tzinfo=timezone.utc)
_SLATE = "ORACLE-20260725-001"
_GAME = "ORACLE-20260725-001-BOS-NYY-746484"
_GAME2 = "ORACLE-20260725-001-LAD-SFG-746485"  # contention: EXACT_REPLAY under 23505
_GAME3 = "ORACLE-20260725-001-CHC-STL-746486"  # contention: CHANGED_INPUT under 23505
_REPO = pathlib.Path(__file__).resolve().parents[2]


# --- Pure validators ---------------------------------------------------------

def test_american_odds_domain():
    for ok in (100, -110, 250, -100):
        assert is_valid_american_odds(ok)
    for bad in (0, 50, -99, 99, True, False, 3.0, "120"):
        assert not is_valid_american_odds(bad)


def test_market_side_normalization():
    assert normalize_market("  ml ") == "ML"
    assert normalize_side(" HOME ") == "home"
    with pytest.raises(ManualPlayValidationError):
        normalize_market("RL")
    with pytest.raises(ManualPlayValidationError):
        normalize_side("draw")


def test_stake_validation():
    assert normalize_stake(1) == Decimal("1")
    assert normalize_stake(Decimal("2.5")) == Decimal("2.5")
    for bad in (True, 0, -1, 2.5, "1"):
        with pytest.raises(ManualPlayValidationError):
            normalize_stake(bad)


def test_deterministic_candidate_label():
    label = build_manual_candidate_id(_GAME, "ML", "home")
    assert label == f"MANUAL-CAND-{_GAME}-ML-home"
    assert build_manual_candidate_id(_GAME, "ML", "home") == label


# --- Sanctioned capability / governed path -----------------------------------

def test_sanctioned_capability_is_playid_capability():
    assert isinstance(im.create_manual_play_id_capability(), im._PlayIdCapability)


def test_unauthorized_play_id_generation_still_raises():
    with pytest.raises(im.UnauthorizedPlayIdGenerationError):
        im.generate_play_id(date(2026, 1, 1), object(), "not-a-capability")


# --- Connection gate (negative checks; no real connection) -------------------

def test_gate_allows_only_task_db_in_test_phase():
    assert evaluate_destination("test", "127.0.0.1", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "10.0.0.5", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5433, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5432, "postgres")[0]
    assert not evaluate_destination("test", "127.0.0.1", 5432, "mlb_test")[0]


def test_gate_maintenance_bounded_and_phase_unset_denies():
    assert evaluate_destination("maintenance", "127.0.0.1", 5432, "postgres")[0]
    assert not evaluate_destination("maintenance", "127.0.0.1", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination(None, "127.0.0.1", 5432, _TEST_DBNAME)[0]


def test_gate_rejects_before_connect_with_sanitized_evidence():
    _attempts.clear()
    set_phase("test")
    sentinel = {"connected": False}

    def _real(*a, **k):
        sentinel["connected"] = True
        return object()

    with pytest.raises(ConnectionRejected):
        guarded_connect(_real, "postgresql://u:secret@evil.example:5432/oracle_manual_play_test")
    assert sentinel["connected"] is False
    assert _attempts and _attempts[-1]["allowed"] is False
    assert "secret" not in _attempts[-1]["dest"] and "***" in _attempts[-1]["dest"]
    set_phase(None)


# --- Mock-connection ordering / replay (no real DB) --------------------------

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "pg_advisory_xact_lock" in s:
            self._result = None
        elif "COUNT(*) FROM oracle_plays WHERE play_id LIKE" in s:
            self._result = (self.conn.play_count,)
        elif "FROM oracle_game_analyses WHERE game_run_id" in s:
            self._result = self.conn.membership
        elif "FROM oracle_plays WHERE origin = 'MANUAL'" in s:
            self._result = self.conn.existing_manual
        elif s.startswith("INSERT INTO oracle_plays"):
            if self.conn.raise_unique:
                exc = Exception("duplicate key"); exc.pgcode = "23505"; raise exc
            self.conn.inserted.append(params)
        elif "INSERT INTO oracle_play_events" in s:
            self.conn.events.append(params)
            self._result = (1,)

    def fetchone(self):
        return self._result

    def close(self):
        pass


class _FakeConn:
    autocommit = False

    def __init__(self, membership=None, existing_manual=None, play_count=0, raise_unique=False):
        self.membership = membership
        self.existing_manual = existing_manual
        self.play_count = play_count
        self.raise_unique = raise_unique
        self.inserted: list = []
        self.events: list = []
        self.committed = 0
        self.rolled = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled += 1


def _record(conn, **over):
    kw = dict(slate_run_id=_SLATE, game_run_id=_GAME, market="ML", selected_side="home",
              odds_at_nomination=120, nomination_timestamp=_TS, current_date_et=date(2026, 7, 25),
              data_origin=CONTEXT_TEST_FIXTURE, env=_ENABLED)
    kw.update(over)
    return record_manual_play(conn, **kw)


def test_kill_switch_first_no_connection_touched():
    class _Boom:
        autocommit = False
        def cursor(self):
            raise AssertionError("connection must not be touched when kill switch is off")
        def rollback(self):
            raise AssertionError("no rollback should occur before any work")
    with pytest.raises(KillSwitchHaltError):
        _record(_Boom(), env={})


def test_recorded_writes_row_and_event_atomically():
    conn = _FakeConn(membership=(_SLATE, "pregame_locked"), existing_manual=None, play_count=0)
    res = _record(conn)
    assert res.outcome == RECORDED
    assert res.play_id == "EO-2026-001"
    assert res.candidate_id == f"MANUAL-CAND-{_GAME}-ML-home"
    assert len(conn.inserted) == 1 and len(conn.events) == 1 and conn.committed == 1
    assert ORIGIN_MANUAL in conn.inserted[0]
    assert conn.events[0][0] == "play_id_assigned"


def test_membership_rejected_before_replay():
    conn = _FakeConn(membership=None)
    with pytest.raises(ManualPlayMembershipError):
        _record(conn)
    assert conn.inserted == [] and conn.events == []
    conn2 = _FakeConn(membership=("ORACLE-20260725-999", "pregame_locked"))
    with pytest.raises(ManualPlayMembershipError):
        _record(conn2)


def test_test_fixture_validation_before_replay():
    conn = _FakeConn(membership=(_SLATE, "pregame_locked"))
    with pytest.raises(ManualPlayValidationError):
        _record(conn, data_origin="LIVE")
    assert conn.inserted == [] and conn.events == []


def test_exact_replay_is_no_write_and_preserves_first_timestamp():
    first_ts = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    conn = _FakeConn(membership=(_SLATE, "pregame_locked"),
                     existing_manual=("EO-2026-001", 120, Decimal("1.0"), first_ts))
    res = _record(conn, nomination_timestamp=_TS)
    assert res.outcome == EXACT_REPLAY
    assert res.nomination_timestamp == first_ts
    assert conn.inserted == [] and conn.events == [] and conn.committed == 0


def test_changed_input_is_no_write_and_reports_divergence():
    first_ts = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    conn = _FakeConn(membership=(_SLATE, "pregame_locked"),
                     existing_manual=("EO-2026-001", 120, Decimal("1.0"), first_ts))
    res = _record(conn, odds_at_nomination=150)
    assert res.outcome == CHANGED_INPUT
    assert res.nomination_timestamp == first_ts
    assert conn.inserted == [] and conn.events == [] and conn.committed == 0
    assert res.divergence["stored_odds_at_nomination"] == 120
    assert res.divergence["supplied_odds_at_nomination"] == 150


def test_concurrency_unique_conflict_reconciles_to_replay():
    first_ts = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
    conn = _FakeConn(membership=(_SLATE, "pregame_locked"), existing_manual=None,
                     play_count=0, raise_unique=True)
    reads = {"n": 0}
    orig_cursor = conn.cursor

    def cursor():
        cur = orig_cursor()
        real_execute = cur.execute

        def execute(sql, params=None):
            s = " ".join(sql.split())
            if "FROM oracle_plays WHERE origin = 'MANUAL'" in s:
                reads["n"] += 1
                cur._result = None if reads["n"] == 1 else ("EO-2026-001", 120, Decimal("1.0"), first_ts)
                return
            return real_execute(sql, params)
        cur.execute = execute
        return cur

    conn.cursor = cursor
    res = _record(conn)
    assert res.outcome == EXACT_REPLAY
    assert conn.committed == 0


# --- Real disposable-DB lifecycle (gated on explicitly approved loopback DSN) --

_APPROVED_DSN = os.environ.get("ORACLE_MANUAL_PLAY_TEST_DSN")


def _maintenance_dsn(dsn: str) -> str:
    u = urlsplit(dsn)
    return urlunsplit((u.scheme, u.netloc, "/" + _MAINT_DBNAME, "", ""))


def _apply_sql_file(cur, path):
    cur.execute(pathlib.Path(path).read_text(encoding="utf-8"))


@pytest.mark.skipif(
    not _APPROVED_DSN,
    reason="disposable-loopback-DB lifecycle requires an explicitly approved DSN in "
           "ORACLE_MANUAL_PLAY_TEST_DSN (role with CREATEDB, host 127.0.0.1:5432, "
           "dbname oracle_manual_play_test); credential discovery/fallback is prohibited",
)
def test_disposable_db_lifecycle():  # pragma: no cover - runs only with approved DSN
    import psycopg2
    from psycopg2 import errors as pgerr

    dsn = _APPROVED_DSN
    host, port, db = parse_destination(dsn)
    assert host in _LOOPBACK_HOSTS and port == 5432 and db == _TEST_DBNAME, "destination not approved"
    maint = _maintenance_dsn(dsn)
    evid = []

    # ABSENT (pre) + ABORT if the task DB already exists.
    set_phase("maintenance")
    mc = psycopg2.connect(maint); mc.autocommit = True
    try:
        cur = mc.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
        assert cur.fetchone() is None, "ABORT: task DB already exists"
        evid.append("absent_pre=True")
        cur.execute(f'CREATE DATABASE "{db}"')
        evid.append("create=ok")
        cur.close()
    finally:
        mc.close(); set_phase(None)

    try:
        set_phase("test")
        tc = psycopg2.connect(dsn); tc.autocommit = False
        try:
            cur = tc.cursor()
            files = [_REPO / "database" / "schema.sql"] + sorted(
                (_REPO / "database" / "migrations").glob("*.sql"))
            for f in files:
                _apply_sql_file(cur, f)
            tc.commit()
            evid.append(f"provision={len(files)}_files")

            # Migration 014 rerunnability (idempotent).
            _apply_sql_file(cur, _REPO / "database" / "migrations"
                            / "014_add_oracle_manual_play_provenance.sql")
            tc.commit(); evid.append("mig014_rerun=ok")

            # Seed fixture-accounting context (slate + game).
            cur.execute(
                "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, "
                "daily_plays_activated, run_started_at) VALUES (%s, %s, %s, %s, %s)",
                (_SLATE, date(2026, 7, 25), "pregame_locked", 0, _TS))
            for gid, ext in ((_GAME, "746484"), (_GAME2, "746485"), (_GAME3, "746486")):
                cur.execute(
                    "INSERT INTO oracle_game_analyses (game_run_id, slate_run_id, external_game_id, "
                    "home_team, away_team, first_pitch_time, game_status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (gid, _SLATE, ext, "NYY", "BOS", _TS, "pregame_locked"))
            tc.commit()

            # CONSTRAINTS: MANUAL-scoped odds CHECK rejects |odds| < 100.
            with pytest.raises(pgerr.CheckViolation):
                cur.execute(
                    "INSERT INTO oracle_plays (play_id, candidate_id, slate_run_id, game_run_id, "
                    "market, selected_side, odds_at_nomination, stake_units, nomination_timestamp, "
                    "play_status, origin) VALUES "
                    "('EO-2026-900','MANUAL-CAND-x','%s','%s','ML','away',50,1.0,%%s,'nominated','MANUAL')"
                    % (_SLATE, _GAME), (_TS,))
            tc.rollback()

            # REPLAY: RECORDED -> EXACT_REPLAY (first ts preserved) -> CHANGED_INPUT.
            r1 = _record(tc)
            assert r1.outcome == RECORDED
            r2 = _record(tc, nomination_timestamp=datetime(2026, 7, 25, 23, 0, tzinfo=timezone.utc))
            assert r2.outcome == EXACT_REPLAY and r2.nomination_timestamp == _TS
            r3 = _record(tc, odds_at_nomination=150)
            assert r3.outcome == CHANGED_INPUT
            evid.append("replay=RECORDED/EXACT_REPLAY/CHANGED_INPUT")

            # DETERMINISTIC TWO-CONNECTION CONTENTION: production 23505 + savepoint recovery.
            # A competing connection commits the SAME MANUAL identity AFTER B's existence-check
            # (injected inside generate_play_id) and BEFORE B's INSERT, forcing a real 23505 on the
            # partial unique index; record_manual_play must ROLLBACK TO SAVEPOINT, re-read, and
            # reconcile to EXACT_REPLAY (same inputs) or CHANGED_INPUT (differing inputs).
            def _contend(game, a_odds, b_odds, a_play_id):
                ca = psycopg2.connect(dsn); ca.autocommit = False  # gate: test-phase, allowed
                orig_gen = mp.generate_play_id
                fired = {"done": False}

                def racing_gen(cur_date, conn, cap):
                    if not fired["done"]:
                        ac = ca.cursor()
                        ac.execute(
                            "INSERT INTO oracle_plays (play_id, candidate_id, slate_run_id, "
                            "game_run_id, market, selected_side, odds_at_nomination, stake_units, "
                            "nomination_timestamp, play_status, origin) VALUES "
                            "(%s,%s,%s,%s,'ML','home',%s,1.0,%s,'nominated','MANUAL')",
                            (a_play_id, f"MANUAL-CAND-{game}-ML-home", _SLATE, game, a_odds, _TS))
                        ac.close(); ca.commit(); fired["done"] = True
                    return orig_gen(cur_date, conn, cap)

                mp.generate_play_id = racing_gen
                try:
                    return record_manual_play(
                        tc, slate_run_id=_SLATE, game_run_id=game, market="ML",
                        selected_side="home", odds_at_nomination=b_odds, nomination_timestamp=_TS,
                        current_date_et=date(2026, 7, 25), data_origin=CONTEXT_TEST_FIXTURE, env=_ENABLED)
                finally:
                    mp.generate_play_id = orig_gen
                    ca.close()

            r_ex = _contend(_GAME2, 120, 120, "EO-2026-500")
            assert r_ex.outcome == EXACT_REPLAY
            r_ch = _contend(_GAME3, 150, 120, "EO-2026-501")
            assert r_ch.outcome == CHANGED_INPUT
            assert r_ch.divergence["stored_odds_at_nomination"] == 150
            evid.append("two_conn_23505=EXACT_REPLAY+CHANGED_INPUT")

            # CONCURRENCY backstop: partial unique index rejects a duplicate MANUAL identity.
            with pytest.raises(pgerr.UniqueViolation):
                cur.execute(
                    "INSERT INTO oracle_plays (play_id, candidate_id, slate_run_id, game_run_id, "
                    "market, selected_side, odds_at_nomination, stake_units, nomination_timestamp, "
                    "play_status, origin) VALUES "
                    "('EO-2026-901','MANUAL-CAND-y','%s','%s','ML','home',120,1.0,%%s,'nominated','MANUAL')"
                    % (_SLATE, _GAME), (_TS,))
            tc.rollback()
            evid.append("unique_index=enforced")

            # ATOMIC ROLLBACK: fail between row insert and event -> neither persists.
            orig_record_event = mp.record_event
            mp.record_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                with pytest.raises(RuntimeError):
                    _record(tc, selected_side="away")
            finally:
                mp.record_event = orig_record_event
            cur.execute("SELECT COUNT(*) FROM oracle_plays WHERE game_run_id=%s AND selected_side='away'",
                        (_GAME,))
            assert cur.fetchone()[0] == 0
            evid.append("atomic_rollback=ok")

            # DESTINATION REJECTION during test phase (reject before connect).
            with pytest.raises(ConnectionRejected):
                psycopg2.connect(_maintenance_dsn(dsn))  # postgres db not allowed in 'test' phase
            evid.append("destination_rejection=ok")
            cur.close()
        finally:
            tc.close(); set_phase(None)
    finally:
        # CLEANUP: drop + verify absent (always attempted).
        set_phase("maintenance")
        mc = psycopg2.connect(maint); mc.autocommit = True
        try:
            cur = mc.cursor()
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", (db,))
            cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
            assert cur.fetchone() is None
            evid.append("drop=ok absent_post=True")
            cur.close()
        finally:
            mc.close(); set_phase(None)

    print("LIFECYCLE_EVIDENCE:", " | ".join(evid))
    assert evid  # lifecycle markers captured for evidence
