"""Acceptance tests for Market-Odds Observation recording (PM-1189).

Connection enforcement is scoped to the disposable lifecycle via the `gate_active()` context
manager and is NEVER installed at import (mirrors the PM-1151 fix in test_manual_play). While
active, tests may reach a database ONLY at 127.0.0.1:5432/oracle_market_odds_test; maintenance
`postgres` is permitted ONLY during the bounded create/drop windows; every destination is validated
and REJECTED BEFORE any connection is opened, with credential-stripped attempt evidence. The
original connector is ALWAYS restored on exit.

The real disposable-DB lifecycle (absent -> create -> provision through 015 -> 015 rerun ->
direct/API/concurrent cases -> drop -> verified absent) runs ONLY when an explicitly approved
loopback DSN is provided in ORACLE_MARKET_ODDS_TEST_DSN, or is derived from an already-approved
loopback DSN in ORACLE_LOOPBACK_TEST_DSN by replacing only the database name with
oracle_market_odds_test. Credential discovery, fallback, and disclosure are prohibited: when no
approved DSN is available the lifecycle skips and no connection is attempted. Pure-logic,
mock-connection, and connection-gate negatives run without any DB.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

# --- Connection-enforcement harness (NOT installed at import) ----------------

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_TEST_DBNAME = "oracle_market_odds_test"
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


class _SecretStr:
    """Carries a credential-bearing DSN whose repr/str are masked, so the raw value
    can never surface through exception text, chaining, or pytest traceback locals.
    The real value is available only via .reveal(), used inline at the connect call."""
    __slots__ = ("_v",)

    def __init__(self, value):
        object.__setattr__(self, "_v", value)

    def reveal(self):
        return self._v

    def __repr__(self):
        return "<dsn redacted>"

    __str__ = __repr__


def _reveal(dsn):
    return dsn.reveal() if isinstance(dsn, _SecretStr) else dsn


def parse_destination(dsn=None, **kw):
    if dsn:
        raw = _reveal(dsn)
        try:
            u = urlsplit(raw)
            return (u.hostname, u.port or 5432, (u.path or "/").lstrip("/"))
        finally:
            raw = None; u = None  # scrub credential-bearing locals from the frame
    return (kw.get("host"), kw.get("port", 5432), kw.get("dbname"))


def sanitize(dsn=None, **kw):
    if dsn:
        raw = _reveal(dsn)
        try:
            u = urlsplit(raw)
            user = (u.username + ":***@") if u.username else ""
            return f"{u.scheme}://{user}{u.hostname or ''}:{u.port or 5432}/{(u.path or '/').lstrip('/')}"
        finally:
            raw = None; u = None  # scrub credential-bearing locals from the frame
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
    try:
        # _reveal(...) is passed inline and never bound to a named local, so the raw
        # DSN cannot appear in this frame's locals; psycopg2.connect is C-level.
        return _real_connect(_reveal(dsn), **kw) if dsn else _real_connect(**kw)
    except Exception:
        # A raw DSN carries credentials; never let it surface in a connect-failure
        # traceback. Re-raise sanitized (from None) so the original frame/args and the
        # exception chain (which a driver could echo the DSN into) are suppressed.
        raise ConnectionError(f"connect failed [{sanitize(dsn, **kw)}]") from None


try:  # pragma: no cover - environment dependent
    import psycopg2 as _pg
    _REAL_CONNECT = _pg.connect  # captured only; NOT patched at import
except Exception:
    _pg = None
    _REAL_CONNECT = None


@contextlib.contextmanager
def gate_active():
    """Install the destination gate over psycopg2.connect for the block, then ALWAYS restore."""
    if _pg is None:
        yield
        return
    original = _pg.connect

    def _wrapped(dsn=None, **kw):
        return guarded_connect(_REAL_CONNECT, dsn, **kw)

    _pg.connect = _wrapped
    try:
        yield
    finally:
        _pg.connect = original
        set_phase(None)


from backend.oracle import odds_observation as oo  # noqa: E402
from backend.oracle.identifier_manager import InvalidConnectionStateError  # noqa: E402
from backend.oracle.odds_observation import (  # noqa: E402
    CORRECTION_NOOP,
    CORRECTION_RECORDED,
    CORRECTION_REPLAY,
    COORD_CONFLICT,
    COORD_EMPTY,
    COORD_RESOLVED,
    CorrectionConflictError,
    CrossLineageError,
    KillSwitchHaltError,
    MalformedLineageError,
    OddsObservationValidationError,
    ROOT_RECORDED,
    ROOT_REPLAY,
    is_valid_american_odds,
    normalize_market,
    normalize_price_format,
    normalize_side,
    normalize_sportsbook,
    read_coordinate,
    record_market_odds_observation,
)

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "1"}
_OBS = datetime(2026, 7, 25, 17, 10, tzinfo=timezone.utc)
_SLATE = "ORACLE-20260725-001"
_GAME = "ORACLE-20260725-001-BOS-NYY-746484"
_GAME2 = "ORACLE-20260725-001-LAD-SFG-746485"
_REPO = pathlib.Path(__file__).resolve().parents[2]


# --- Pure validators (no DB) -------------------------------------------------

def test_american_odds_domain():
    for ok in (100, -110, 250, -100):
        assert is_valid_american_odds(ok)
    for bad in (0, 50, -99, 99, True, False, 3.0, "120"):
        assert not is_valid_american_odds(bad)


def test_vocabulary_normalization():
    assert normalize_market("  ml ") == "ML"
    assert normalize_side(" HOME ") == "home"
    assert normalize_price_format(" AMERICAN ") == "american"
    assert normalize_sportsbook(" draftkings ") == "DRAFTKINGS"
    for bad in ("RL", "spread"):
        with pytest.raises(OddsObservationValidationError):
            normalize_market(bad)
    with pytest.raises(OddsObservationValidationError):
        normalize_side("draw")
    with pytest.raises(OddsObservationValidationError):
        normalize_price_format("decimal")
    for bad in ("bet 365", "book!", ""):
        with pytest.raises(OddsObservationValidationError):
            normalize_sportsbook(bad)


# --- Mock connection ---------------------------------------------------------

def _predecessor(pid, price, coord=None):
    c = coord or (_GAME, "DRAFTKINGS", "ML", "home", "american", _OBS,
                  "market_odds_fixture", "TEST_FIXTURE")
    return (pid, c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], price)


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = None
        self._rows = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "pg_advisory_xact_lock" in s:
            self._result = None
        elif s.startswith(("SAVEPOINT", "ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT")):
            self._result = None
        elif "WHERE supersedes_observation_id IS NULL AND game_run_id" in s:
            self._result = self.conn.root_exact
        elif s.startswith("SELECT observation_id, price FROM oracle_market_odds_observations "
                          "WHERE supersedes_observation_id"):
            self._result = self.conn.child
        elif "FROM oracle_market_odds_observations WHERE observation_id =" in s:
            self._result = self.conn.predecessor
        elif "NOT EXISTS" in s:
            self._rows = list(self.conn.heads)
        elif s.startswith("INSERT INTO oracle_market_odds_observations"):
            if self.conn.raise_unique:
                exc = Exception("duplicate key"); exc.pgcode = "23505"; raise exc
            self.conn.inserted.append(params)
            self._result = (self.conn.next_id,)

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    autocommit = False

    def __init__(self, root_exact=None, predecessor=None, child=None, heads=(),
                 next_id=10, raise_unique=False):
        self.root_exact = root_exact
        self.predecessor = predecessor
        self.child = child
        self.heads = heads
        self.next_id = next_id
        self.raise_unique = raise_unique
        self.inserted: list = []
        self.committed = 0
        self.rolled = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled += 1


def _call(conn, **over):
    kw = dict(game_run_id=_GAME, sportsbook="DRAFTKINGS", market="ML", selected_side="home",
              price_format="american", price=120, source="market_odds_fixture",
              data_origin="TEST_FIXTURE", observed_at=_OBS, env=_ENABLED)
    kw.update(over)
    return record_market_odds_observation(conn, **kw)


def test_kill_switch_first_no_connection_touched():
    class _Boom:
        autocommit = False
        def cursor(self):
            raise AssertionError("connection must not be touched when kill switch is off")
        def rollback(self):
            raise AssertionError("no rollback before any work")
    with pytest.raises(KillSwitchHaltError):
        _call(_Boom(), env={})


def test_autocommit_rejected():
    class _AC:
        autocommit = True
    with pytest.raises(InvalidConnectionStateError):
        _call(_AC())


def test_input_validation():
    conn = _FakeConn()
    with pytest.raises(OddsObservationValidationError):
        _call(conn, game_run_id="not-a-game")
    with pytest.raises(OddsObservationValidationError):
        _call(conn, price=50)
    with pytest.raises(OddsObservationValidationError):
        _call(conn, price=True)
    with pytest.raises(OddsObservationValidationError):
        _call(conn, source="the_odds_api")
    with pytest.raises(OddsObservationValidationError):
        _call(conn, data_origin="LIVE_PROVIDER")   # reserved / inert
    with pytest.raises(OddsObservationValidationError):
        _call(conn, data_origin="AUTHENTICATED_HISTORICAL")
    with pytest.raises(OddsObservationValidationError):
        _call(conn, observed_at=datetime(2026, 7, 25, 17, 10))  # naive
    with pytest.raises(OddsObservationValidationError):
        _call(conn, supersedes_observation_id=0)
    assert conn.inserted == []


def test_root_recorded():
    conn = _FakeConn(root_exact=None, next_id=10)
    res = _call(conn)
    assert res.outcome == ROOT_RECORDED and res.observation_id == 10
    assert len(conn.inserted) == 1 and conn.committed == 0 and conn.rolled == 0


def test_root_exact_replay_no_write():
    conn = _FakeConn(root_exact=(7,))
    res = _call(conn)
    assert res.outcome == ROOT_REPLAY and res.observation_id == 7
    assert conn.inserted == [] and conn.committed == 0 and conn.rolled == 0


def test_correction_recorded():
    conn = _FakeConn(predecessor=_predecessor(5, 120), child=None, next_id=11)
    res = _call(conn, price=140, supersedes_observation_id=5)
    assert res.outcome == CORRECTION_RECORDED and res.observation_id == 11
    assert res.supersedes_observation_id == 5 and len(conn.inserted) == 1


def test_identical_child_replay_before_stale_head():
    conn = _FakeConn(predecessor=_predecessor(5, 120), child=(6, 140))
    res = _call(conn, price=140, supersedes_observation_id=5)
    assert res.outcome == CORRECTION_REPLAY and res.observation_id == 6
    assert conn.inserted == [] and conn.committed == 0 and conn.rolled == 0


def test_differing_competing_child_conflict():
    conn = _FakeConn(predecessor=_predecessor(5, 120), child=(6, 140))
    with pytest.raises(CorrectionConflictError):
        _call(conn, price=150, supersedes_observation_id=5)
    assert conn.inserted == [] and conn.rolled == 0 and conn.committed == 0


def test_same_price_correction_noop():
    conn = _FakeConn(predecessor=_predecessor(5, 120), child=None)
    res = _call(conn, price=120, supersedes_observation_id=5)
    assert res.outcome == CORRECTION_NOOP and res.observation_id == 5
    assert conn.inserted == [] and conn.committed == 0 and conn.rolled == 0


def test_cross_lineage_rejected():
    other = (_GAME, "FANDUEL", "ML", "home", "american", _OBS,
             "market_odds_fixture", "TEST_FIXTURE")
    conn = _FakeConn(predecessor=_predecessor(5, 120, coord=other), child=None)
    with pytest.raises(CrossLineageError):
        _call(conn, price=140, supersedes_observation_id=5)
    assert conn.inserted == [] and conn.rolled == 0 and conn.committed == 0


def test_malformed_missing_predecessor():
    conn = _FakeConn(predecessor=None)
    with pytest.raises(MalformedLineageError):
        _call(conn, price=140, supersedes_observation_id=999)
    assert conn.rolled == 0 and conn.committed == 0


def test_root_unique_conflict_reconciles_to_replay():
    # First find returns None (insert path); insert raises 23505; re-read returns the row.
    conn = _FakeConn(root_exact=None, raise_unique=True)
    reads = {"n": 0}
    orig_cursor = conn.cursor

    def cursor():
        cur = orig_cursor()
        real = cur.execute

        def execute(sql, params=None):
            s = " ".join(sql.split())
            if "WHERE supersedes_observation_id IS NULL AND game_run_id" in s:
                reads["n"] += 1
                cur._result = None if reads["n"] == 1 else (42,)
                return
            return real(sql, params)
        cur.execute = execute
        return cur

    conn.cursor = cursor
    res = _call(conn)
    assert res.outcome == ROOT_REPLAY and res.observation_id == 42


def test_child_unique_conflict_differing_is_conflict():
    conn = _FakeConn(predecessor=_predecessor(5, 120), child=None, raise_unique=True)
    reads = {"n": 0}
    orig_cursor = conn.cursor

    def cursor():
        cur = orig_cursor()
        real = cur.execute

        def execute(sql, params=None):
            s = " ".join(sql.split())
            if s.startswith("SELECT observation_id, price FROM oracle_market_odds_observations "
                            "WHERE supersedes_observation_id"):
                reads["n"] += 1
                cur._result = None if reads["n"] == 1 else (77, 199)  # a different price appeared
                return
            return real(sql, params)
        cur.execute = execute
        return cur

    conn.cursor = cursor
    with pytest.raises(CorrectionConflictError):
        _call(conn, price=140, supersedes_observation_id=5)


def test_read_coordinate_status():
    def _read(conn):
        return read_coordinate(
            conn, game_run_id=_GAME, sportsbook="DRAFTKINGS", market="ML",
            selected_side="home", price_format="american", observed_at=_OBS,
            source="market_odds_fixture", data_origin="TEST_FIXTURE",
        )
    assert _read(_FakeConn(heads=())).status == COORD_EMPTY
    assert _read(_FakeConn(heads=[(1, 120)])).status == COORD_RESOLVED
    conflict = _read(_FakeConn(heads=[(1, 120), (2, 140)]))
    assert conflict.status == COORD_CONFLICT and len(conflict.heads) == 2


# --- Connection gate negatives (no real connection) --------------------------

def test_gate_allows_only_task_db_in_test_phase():
    assert evaluate_destination("test", "127.0.0.1", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "10.0.0.5", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5433, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5432, "postgres")[0]


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
        guarded_connect(_real, "postgresql://u:secret@evil.example:5432/oracle_market_odds_test")
    assert sentinel["connected"] is False
    assert _attempts and _attempts[-1]["allowed"] is False
    assert "secret" not in _attempts[-1]["dest"] and "***" in _attempts[-1]["dest"]
    set_phase(None)


def test_import_does_not_globally_patch_connect():
    if _pg is None:
        pytest.skip("psycopg2 not importable")
    assert _pg.connect is _REAL_CONNECT


def test_gate_active_restores_on_failure():
    if _pg is None:
        pytest.skip("psycopg2 not importable")
    with pytest.raises(RuntimeError):
        with gate_active():
            assert _pg.connect is not _REAL_CONNECT
            raise RuntimeError("boom inside gated block")
    assert _pg.connect is _REAL_CONNECT


def test_synthetic_secret_never_disclosed(capsys):
    # Regression: a credential must never surface via repr/str, sanitized evidence,
    # exception text, exception chaining, or captured stdout/stderr.
    if _pg is None:
        pytest.skip("psycopg2 not importable")
    synthetic = "SYNTHETIC_PW_DO_NOT_LOG_7f3a9e"
    secret = _SecretStr(f"postgresql://svc:{synthetic}@127.0.0.1:5432/{_TEST_DBNAME}")
    # (1) masked repr/str + sanitized destination
    assert synthetic not in repr(secret) and synthetic not in str(secret)
    assert synthetic not in sanitize(secret)
    assert parse_destination(secret) == ("127.0.0.1", 5432, _TEST_DBNAME)
    # (2) forced connect failure whose driver error ECHOES the raw DSN must not leak it
    def _boom(*a, **k):
        raise RuntimeError(secret.reveal())  # worst case: driver echoes the DSN
    set_phase("test")
    try:
        with pytest.raises(ConnectionError) as ei:
            guarded_connect(_boom, secret)
    finally:
        set_phase(None)
    assert synthetic not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__ is True
    # (3) absent from captured stdout/stderr (only masked forms are ever emitted)
    print("dest:", sanitize(secret), repr(secret))
    captured = capsys.readouterr()
    assert synthetic not in captured.out and synthetic not in captured.err


# --- Real disposable-DB lifecycle (gated on an explicitly approved loopback DSN) ---

def _resolve_approved_dsn():
    explicit = os.environ.get("ORACLE_MARKET_ODDS_TEST_DSN")
    if explicit:
        try:
            return _SecretStr(explicit)
        finally:
            explicit = None
    base = os.environ.get("ORACLE_LOOPBACK_TEST_DSN")
    if not base:
        return None
    try:
        u = urlsplit(base)
        return _SecretStr(urlunsplit((u.scheme, u.netloc, "/" + _TEST_DBNAME, "", "")))
    finally:
        base = None; u = None


_APPROVED_DSN = _resolve_approved_dsn()  # _SecretStr | None (masked repr)


def _maintenance_dsn(dsn):
    raw = _reveal(dsn)
    try:
        u = urlsplit(raw)
        return _SecretStr(urlunsplit((u.scheme, u.netloc, "/" + _MAINT_DBNAME, "", "")))
    finally:
        raw = None; u = None


def _apply_sql_file(cur, path):
    cur.execute(pathlib.Path(path).read_text(encoding="utf-8"))


@pytest.mark.skipif(
    not _APPROVED_DSN,
    reason="disposable-loopback-DB lifecycle requires an explicitly approved DSN in "
           "ORACLE_MARKET_ODDS_TEST_DSN (or ORACLE_LOOPBACK_TEST_DSN to derive by dbname), "
           "role with CREATEDB, host 127.0.0.1:5432, dbname oracle_market_odds_test; "
           "credential discovery/fallback is prohibited",
)
def test_disposable_db_lifecycle():  # pragma: no cover - runs only with approved DSN
    import psycopg2
    from psycopg2 import errors as pgerr

    dsn = _APPROVED_DSN
    host, port, db = parse_destination(dsn)
    assert host in _LOOPBACK_HOSTS and port == 5432 and db == _TEST_DBNAME, "destination not approved"
    maint = _maintenance_dsn(dsn)
    evid = []

    def _seed(cur):
        cur.execute(
            "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, "
            "daily_plays_activated, run_started_at) VALUES (%s, %s, %s, %s, %s)",
            (_SLATE, _OBS.date(), "pregame_locked", 0, _OBS))
        for gid, ext in ((_GAME, "746484"), (_GAME2, "746485")):
            cur.execute(
                "INSERT INTO oracle_game_analyses (game_run_id, slate_run_id, external_game_id, "
                "home_team, away_team, first_pitch_time, game_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (gid, _SLATE, ext, "NYY", "BOS", _OBS, "pregame_locked"))

    def _rec(tc, **over):
        kw = dict(game_run_id=_GAME, sportsbook="DRAFTKINGS", market="ML", selected_side="home",
                  price_format="american", price=120, source="market_odds_fixture",
                  data_origin="TEST_FIXTURE", observed_at=_OBS, env=_ENABLED)
        kw.update(over)
        return record_market_odds_observation(tc, **kw)

    try:
        with gate_active():
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
                mc.close()

            set_phase("test")
            tc = psycopg2.connect(dsn); tc.autocommit = False
            try:
                cur = tc.cursor()
                files = [_REPO / "database" / "schema.sql"] + sorted(
                    (_REPO / "database" / "migrations").glob("*.sql"))
                for f in files:
                    _apply_sql_file(cur, f)
                tc.commit()
                evid.append(f"provision={len(files)}_files_through_015")

                # 015 rerunnability (idempotent).
                _apply_sql_file(cur, _REPO / "database" / "migrations"
                                / "015_add_oracle_market_odds_observations.sql")
                tc.commit(); evid.append("mig015_rerun=ok")

                _seed(cur); tc.commit()

                # DOMAIN / VOCAB / PROVENANCE / FK CHECK proofs (direct inserts).
                base_cols = ("game_run_id, sportsbook, market, selected_side, price_format, "
                             "price, source, data_origin, observed_at")
                def _direct(values_sql, params):
                    cur.execute(
                        f"INSERT INTO oracle_market_odds_observations ({base_cols}) VALUES {values_sql}",
                        params)
                for bad, params in [
                    ("(%s,%s,'RL','home','american',120,'market_odds_fixture','TEST_FIXTURE',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                              # market
                    ("(%s,%s,'ML','draw','american',120,'market_odds_fixture','TEST_FIXTURE',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                              # side
                    ("(%s,%s,'ML','home','decimal',120,'market_odds_fixture','TEST_FIXTURE',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                              # price_format
                    ("(%s,%s,'ML','home','american',50,'market_odds_fixture','TEST_FIXTURE',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                              # american domain
                    ("(%s,%s,'ML','home','american',120,'the_odds_api','TEST_FIXTURE',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                             # source freeze
                    ("(%s,%s,'ML','home','american',120,'market_odds_fixture','LIVE_PROVIDER',%s)",
                     (_GAME, "DRAFTKINGS", _OBS)),                             # admission (inert)
                    ("(%s,%s,'ML','home','american',120,'market_odds_fixture','TEST_FIXTURE',%s)",
                     (_GAME, "bad book", _OBS)),                               # sportsbook token
                ]:
                    with pytest.raises(pgerr.CheckViolation):
                        _direct(bad, params)
                    tc.rollback()
                with pytest.raises(pgerr.ForeignKeyViolation):
                    _direct("(%s,%s,'ML','home','american',120,'market_odds_fixture','TEST_FIXTURE',%s)",
                            ("ORACLE-20260725-001-XXX-YYY-999999", "DRAFTKINGS", _OBS))
                tc.rollback()
                evid.append("domain/vocab/provenance/fk=enforced")

                # FORCED ingestion time vs malicious direct insert: supplied value discarded.
                cur.execute("SELECT clock_timestamp()"); t0 = cur.fetchone()[0]
                fake_future = _OBS + timedelta(days=100)
                cur.execute(
                    "INSERT INTO oracle_market_odds_observations "
                    "(game_run_id, sportsbook, market, selected_side, price_format, price, source, "
                    "data_origin, observed_at, ingested_at) VALUES "
                    "(%s,'DRAFTKINGS','ML','away','american',120,'market_odds_fixture','TEST_FIXTURE',%s,%s) "
                    "RETURNING observation_id, ingested_at",
                    (_GAME, _OBS, fake_future))
                _oid, stored_ing = cur.fetchone()
                cur.execute("SELECT clock_timestamp()"); t1 = cur.fetchone()[0]
                assert t0 <= stored_ing <= t1, "ingested_at must be forced to clock_timestamp()"
                assert stored_ing < fake_future
                tc.commit()
                # A future observation cannot be admitted by faking ingested_at.
                with pytest.raises(pgerr.CheckViolation):
                    cur.execute(
                        "INSERT INTO oracle_market_odds_observations "
                        "(game_run_id, sportsbook, market, selected_side, price_format, price, source, "
                        "data_origin, observed_at, ingested_at) VALUES "
                        "(%s,'DRAFTKINGS','ML','away','american',120,'market_odds_fixture','TEST_FIXTURE',"
                        "%s,%s)",
                        (_GAME, fake_future, fake_future + timedelta(days=1)))
                tc.rollback()
                evid.append("forced_ingest_time=ok future_rejected=ok")

                # APPEND-ONLY denial.
                cur.execute("SELECT observation_id FROM oracle_market_odds_observations LIMIT 1")
                any_id = cur.fetchone()[0]
                with pytest.raises(Exception):
                    cur.execute("UPDATE oracle_market_odds_observations SET price=200 WHERE observation_id=%s",
                                (any_id,))
                tc.rollback()
                with pytest.raises(Exception):
                    cur.execute("DELETE FROM oracle_market_odds_observations WHERE observation_id=%s",
                                (any_id,))
                tc.rollback()
                evid.append("append_only=enforced")

                # ROOT record + exact replay.
                r1 = _rec(tc); assert r1.outcome == ROOT_RECORDED
                r2 = _rec(tc); assert r2.outcome == ROOT_REPLAY and r2.observation_id == r1.observation_id
                evid.append("root_record+exact_replay=ok")

                # Retained differing-price roots -> coordinate CONFLICT.
                r3 = _rec(tc, price=140); assert r3.outcome == ROOT_RECORDED
                cr = read_coordinate(tc, game_run_id=_GAME, sportsbook="DRAFTKINGS", market="ML",
                                     selected_side="home", price_format="american", observed_at=_OBS,
                                     source="market_odds_fixture", data_origin="TEST_FIXTURE")
                assert cr.status == COORD_CONFLICT and len(cr.heads) == 2
                evid.append("retained_root_conflict=ok")

                # Independent linear correction chain on the first root; child replay / conflict / noop.
                c1 = _rec(tc, price=160, supersedes_observation_id=r1.observation_id)
                assert c1.outcome == CORRECTION_RECORDED
                c2 = _rec(tc, price=160, supersedes_observation_id=r1.observation_id)  # identical child
                assert c2.outcome == CORRECTION_REPLAY and c2.observation_id == c1.observation_id
                with pytest.raises(CorrectionConflictError):  # differing competing child
                    _rec(tc, price=175, supersedes_observation_id=r1.observation_id)
                noop = _rec(tc, price=140, supersedes_observation_id=r3.observation_id)  # same-price head
                assert noop.outcome == CORRECTION_NOOP
                evid.append("child_replay/conflict/noop=ok")

                # Stale-head + cross-lineage rejection.
                with pytest.raises(CorrectionConflictError):  # r1 already superseded by c1
                    _rec(tc, price=180, supersedes_observation_id=r1.observation_id)
                with pytest.raises(CrossLineageError):        # different sportsbook coordinate
                    _rec(tc, sportsbook="FANDUEL", price=155, supersedes_observation_id=c1.observation_id)
                evid.append("stale/cross_lineage=rejected")
                tc.commit()  # caller persists the acceptance-case rows (recorder never commits)
                evid.append("caller_commit_persists=ok")

                # ============================================================
                # TRANSACTION OWNERSHIP (PM-1191): the recorder never commits/rolls back
                # the caller's transaction; a witness connection proves visibility timing.
                # ============================================================
                def _count(conn, book):
                    q = conn.cursor()
                    try:
                        q.execute("SELECT COUNT(*) FROM oracle_market_odds_observations "
                                  "WHERE game_run_id=%s AND sportsbook=%s", (_GAME2, book))
                        return q.fetchone()[0]
                    finally:
                        q.close()

                ca = psycopg2.connect(dsn); ca.autocommit = False
                cw = psycopg2.connect(dsn); cw.autocommit = True   # witness
                try:
                    def _rca(book, **o):
                        kw = dict(game_run_id=_GAME2, sportsbook=book, market="ML",
                                  selected_side="home", price_format="american", price=120,
                                  source="market_odds_fixture", data_origin="TEST_FIXTURE",
                                  observed_at=_OBS, env=_ENABLED)
                        kw.update(o)
                        return record_market_odds_observation(ca, **kw)

                    # (1) recorded observation persists ONLY after caller commit
                    assert _rca("OWNCOMMIT").outcome == ROOT_RECORDED
                    assert _count(cw, "OWNCOMMIT") == 0        # recorder did NOT self-commit
                    ca.commit()
                    assert _count(cw, "OWNCOMMIT") == 1
                    # (2) caller rollback removes the observation
                    assert _rca("OWNROLLBACK").outcome == ROOT_RECORDED
                    ca.rollback()
                    assert _count(cw, "OWNROLLBACK") == 0
                    # (3) replay/no-op does NOT commit unrelated caller work
                    assert _rca("OWNBASE").outcome == ROOT_RECORDED; ca.commit()
                    assert _rca("OWNUNREL").outcome == ROOT_RECORDED     # unrelated, uncommitted
                    assert _rca("OWNBASE").outcome == ROOT_REPLAY        # replay/no-op
                    assert _count(cw, "OWNUNREL") == 0                   # replay did not commit it
                    ca.rollback()
                    assert _count(cw, "OWNUNREL") == 0
                    # (4) recoverable recorder failure preserves unrelated work; tx stays controllable
                    assert _rca("OWNKEEP").outcome == ROOT_RECORDED      # unrelated, uncommitted
                    _orig_insert = oo._insert
                    oo._insert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("recoverable"))
                    try:
                        with pytest.raises(RuntimeError):
                            _rca("OWNFAIL")
                    finally:
                        oo._insert = _orig_insert
                    assert _count(ca, "OWNKEEP") == 1                    # tx not aborted; unrelated work intact
                    ca.commit()                                         # caller still controls the tx
                    assert _count(cw, "OWNKEEP") == 1 and _count(cw, "OWNFAIL") == 0
                    # (5) atomic composition inside ONE caller-owned transaction
                    a1 = _rca("OWNATOMIC")
                    a2 = _rca("OWNATOMIC", price=150, supersedes_observation_id=a1.observation_id)
                    assert a1.outcome == ROOT_RECORDED and a2.outcome == CORRECTION_RECORDED
                    assert _count(cw, "OWNATOMIC") == 0
                    ca.commit()
                    assert _count(cw, "OWNATOMIC") == 2
                finally:
                    ca.close(); cw.close()
                evid.append("txn_ownership: commit_persists/rollback_removes/replay_no_commit/"
                            "failure_preserves+controllable/atomic=ok")

                # ============================================================
                # REAL two-connection / independent-transaction CONTENTION.
                # Proves blocking + serialization + reconciliation ordering (bounded;
                # fails rather than hanging). Not mocks, not lock-acquisition alone.
                # ============================================================
                import threading, time

                def _bg(fn):
                    started = threading.Event(); box = {}
                    def run():
                        started.set()
                        try:
                            box["ok"] = fn()
                        except Exception as e:      # captured; asserted by caller
                            box["err"] = e
                    th = threading.Thread(target=run, daemon=True); th.start()
                    assert started.wait(5), "worker thread did not start"
                    return th, box

                def _mk(conn, book, **o):
                    kw = dict(game_run_id=_GAME2, sportsbook=book, market="ML",
                              selected_side="home", price_format="american",
                              source="market_odds_fixture", data_origin="TEST_FIXTURE",
                              observed_at=_OBS, env=_ENABLED)
                    kw.update(o)
                    return record_market_odds_observation(conn, **kw)

                # (1) identical ROOT race: A holds; B blocks; after A commits B -> exact replay; one root.
                book = "RACE1ROOT"
                cA = psycopg2.connect(dsn); cA.autocommit = False
                cB = psycopg2.connect(dsn); cB.autocommit = False
                try:
                    for c in (cA, cB):
                        cc = c.cursor(); cc.execute("SET lock_timeout='15000ms'"); cc.close()
                    assert _mk(cA, book, price=120).outcome == ROOT_RECORDED    # A holds coordinate lock
                    th, box = _bg(lambda: _mk(cB, book, price=120))
                    time.sleep(1.0)
                    assert th.is_alive() and not box, "B must block until A commits"
                    cA.commit()
                    th.join(15); assert not th.is_alive(), "B did not complete after A commit (deadlock?)"
                    assert "err" not in box and box["ok"].outcome == ROOT_REPLAY
                    cB.commit()
                    rq = cB.cursor()
                    rq.execute("SELECT COUNT(*) FROM oracle_market_odds_observations WHERE game_run_id=%s "
                               "AND sportsbook=%s AND supersedes_observation_id IS NULL", (_GAME2, book))
                    assert rq.fetchone()[0] == 1; rq.close()
                finally:
                    cA.close(); cB.close()
                evid.append("race_identical_root: B_blocked->exact_replay, one_root=ok")

                def _child_race(book, a_price, b_price, expect):
                    cP = psycopg2.connect(dsn); cP.autocommit = False
                    cA2 = psycopg2.connect(dsn); cA2.autocommit = False
                    cB2 = psycopg2.connect(dsn); cB2.autocommit = False
                    try:
                        for c in (cA2, cB2):
                            cc = c.cursor(); cc.execute("SET lock_timeout='15000ms'"); cc.close()
                        rP = _mk(cP, book, price=100); assert rP.outcome == ROOT_RECORDED
                        cP.commit(); pid = rP.observation_id
                        assert _mk(cA2, book, price=a_price,
                                   supersedes_observation_id=pid).outcome == CORRECTION_RECORDED
                        th, box = _bg(lambda: _mk(cB2, book, price=b_price, supersedes_observation_id=pid))
                        time.sleep(1.0)
                        assert th.is_alive() and not box, "B must block until A commits"
                        cA2.commit()
                        th.join(15); assert not th.is_alive(), "B did not complete after A commit (deadlock?)"
                        q = cB2.cursor()
                        q.execute("SELECT price FROM oracle_market_odds_observations "
                                  "WHERE supersedes_observation_id=%s", (pid,))
                        rows = q.fetchall(); q.close()
                        assert len(rows) == 1 and rows[0][0] == a_price, "winner child preserved; exactly one"
                        if expect == "replay":
                            assert "err" not in box and box["ok"].outcome == CORRECTION_REPLAY
                        else:
                            assert "ok" not in box and isinstance(box.get("err"), CorrectionConflictError)
                        cB2.rollback()
                    finally:
                        cP.close(); cA2.close(); cB2.close()

                # (2) identical CHILD race -> identical-child replay (before stale-head); one child.
                _child_race("RACE2CHILD", 150, 150, "replay")
                evid.append("race_identical_child: B_blocked->identical_replay, one_child=ok")
                # (3) differing competing CHILD race -> CORRECTION_CONFLICT; winner preserved; one child.
                _child_race("RACE3CHILD", 150, 175, "conflict")
                evid.append("race_differing_child: B_blocked->CORRECTION_CONFLICT, one_child_winner=ok")

                # ADVISORY-LOCK contention: a second session cannot take the same coordinate lock.
                key_sql = ("SELECT pg_try_advisory_xact_lock(%s, hashtext(%s))")
                coord_key = oo._coordinate_key(_GAME, "DRAFTKINGS", "ML", "home", "american",
                                               _OBS, "market_odds_fixture", "TEST_FIXTURE")
                cur.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (oo._LOCK_NS_MOO, coord_key))
                other = psycopg2.connect(dsn); other.autocommit = False
                try:
                    oc = other.cursor()
                    oc.execute(key_sql, (oo._LOCK_NS_MOO, coord_key))
                    assert oc.fetchone()[0] is False, "second session must not acquire the coordinate lock"
                    other.rollback()
                finally:
                    other.close()
                tc.rollback()
                evid.append("advisory_lock_race=serialized")

                # ATOMIC ROLLBACK: failure mid-op persists nothing.
                orig_insert = oo._insert
                oo._insert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                try:
                    cur.execute("SELECT COUNT(*) FROM oracle_market_odds_observations "
                                "WHERE game_run_id=%s AND sportsbook='FANDUEL'", (_GAME,))
                    before = cur.fetchone()[0]
                    with pytest.raises(RuntimeError):
                        _rec(tc, sportsbook="FANDUEL", price=133)
                    cur.execute("SELECT COUNT(*) FROM oracle_market_odds_observations "
                                "WHERE game_run_id=%s AND sportsbook='FANDUEL'", (_GAME,))
                    assert cur.fetchone()[0] == before
                finally:
                    oo._insert = orig_insert
                evid.append("atomic_rollback=ok")

                # DESTINATION rejection during test phase.
                with pytest.raises(ConnectionRejected):
                    psycopg2.connect(_maintenance_dsn(dsn))
                evid.append("destination_rejection=ok")
                cur.close()
            finally:
                tc.close()

        # Gate RESTORED. Prove restoration + unrelated DB access (ungated).
        assert _pg.connect is _REAL_CONNECT, "connector not restored after gate_active"
        evid.append("connector_restored=True")
        set_phase(None)
        cu = psycopg2.connect(_reveal(dsn)); cu.autocommit = True  # ungated: reveal inline only
        try:
            ucur = cu.cursor()
            ucur.execute("SELECT COUNT(*) FROM oracle_market_odds_observations")
            _ = ucur.fetchone()
            ucur.close()
            evid.append("unrelated_db_after_restore=ok")
        finally:
            cu.close()
    finally:
        # CLEANUP: drop + verify absent (gated; always attempted).
        with gate_active():
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
                mc.close()

    print("LIFECYCLE_EVIDENCE:", " | ".join(evid))
    assert evid
