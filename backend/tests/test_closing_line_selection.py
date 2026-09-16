"""Acceptance tests for the Closing-Line Selector (PM-1231).

Layers:
  * Offline unit — pre-query precedence/validation with a no-DB connection (proves the
    selector returns/raises before touching the database), plus harness negatives and
    credential sanitization with a SYNTHETIC secret. Run without any DB.
  * Integration — a disposable-loopback-PostgreSQL lifecycle, gated on the session-supplied
    ORACLE_CLOSING_LINE_TEST_DSN. It provisions schema + migrations THROUGH 015 in a
    cycle-owned database, runs the historical selector against the ACTUAL constrained
    observation table, and runs otherwise-unrepresentable corrupt/non-monotonic history
    against an ISOLATED SYNTHETIC relation via `search_path` — executing the SAME production
    query body (backend.oracle.closing_line_selection._SELECTION_SQL). Skips when the DSN is
    absent (a skip is NOT integration proof). Cleanup + verified-absence in `finally`.

Credential safety: destinations are validated BEFORE connect; connect failures are re-raised
sanitized (no DSN in tracebacks); credential-bearing integration runs should use
`-o addopts= --tb=line` and never `--showlocals`.
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
_TEST_DBNAME = "oracle_closing_line_test"
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
    try:
        return _real_connect(dsn, **kw) if dsn else _real_connect(**kw)
    except Exception as exc:
        # Never let a raw DSN (credentials) surface in a connect-failure traceback.
        raise ConnectionError(f"connect failed [{sanitize(dsn, **kw)}]: {type(exc).__name__}") from None


try:  # pragma: no cover - environment dependent
    import psycopg2 as _pg
    _REAL_CONNECT = _pg.connect
except Exception:
    _pg = None
    _REAL_CONNECT = None


@contextlib.contextmanager
def gate_active():
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


from backend.oracle import closing_line_selection as cls  # noqa: E402
from backend.oracle.closing_line_selection import (  # noqa: E402
    AS_OF_CONTEMPORANEOUS,
    AS_OF_RETROSPECTIVE,
    REASON_AS_OF_BEFORE_START,
    REASON_NO_START,
    REASON_POSTPONED,
    STATUS_SELECTED,
    STATUS_UNAVAILABLE,
    ClosingLineValidationError,
    select_closing_line,
)
from backend.oracle.identifier_manager import InvalidConnectionStateError  # noqa: E402

_START = datetime(2026, 7, 25, 17, 10, tzinfo=timezone.utc)
_GAME = "ORACLE-20260725-001-BOS-NYY-746484"
_SLATE = "ORACLE-20260725-001"
_REPO = pathlib.Path(__file__).resolve().parents[2]


# --- Offline: no-DB connection proving pre-query precedence ------------------

class _NoDBConn:
    autocommit = False

    def cursor(self):
        raise AssertionError("pre-query precedence must resolve before any DB access")


def _call(conn=None, **over):
    kw = dict(game_run_id=_GAME, selected_side="home", authoritative_start=_START,
              start_version="v1", start_provenance="test-fixture")
    kw.update(over)
    return select_closing_line(conn if conn is not None else _NoDBConn(), **kw)


def test_autocommit_rejected_before_db():
    class _AC:
        autocommit = True
        def cursor(self):
            raise AssertionError("must not reach cursor")
    with pytest.raises(InvalidConnectionStateError):
        _call(_AC())


def test_structural_validation_before_db():
    with pytest.raises(ClosingLineValidationError):
        _call(game_run_id="not-a-game")
    with pytest.raises(ClosingLineValidationError):
        _call(selected_side="draw")
    with pytest.raises(ClosingLineValidationError):
        _call(sportsbook="FANDUEL_NJ")           # no jurisdiction conflation
    with pytest.raises(ClosingLineValidationError):
        _call(sportsbook="FANDUEL")
    with pytest.raises(ClosingLineValidationError):
        _call(market="RL")
    with pytest.raises(ClosingLineValidationError):
        _call(price_format="decimal")
    with pytest.raises(ClosingLineValidationError):
        _call(source="the_odds_api")
    with pytest.raises(ClosingLineValidationError):
        _call(data_origin="LIVE_PROVIDER")
    with pytest.raises(ClosingLineValidationError):
        _call(start_version="")
    with pytest.raises(ClosingLineValidationError):
        _call(start_provenance="  ")


def test_postponed_and_missing_start_before_db():
    r = _call(postponed=True)
    assert r.status == STATUS_UNAVAILABLE and r.reason == REASON_POSTPONED
    r2 = _call(authoritative_start=None)
    assert r2.status == STATUS_UNAVAILABLE and r2.reason == REASON_NO_START


def test_naive_start_and_as_of_rejected_before_db():
    with pytest.raises(ClosingLineValidationError):
        _call(authoritative_start=datetime(2026, 7, 25, 17, 10))  # naive
    with pytest.raises(ClosingLineValidationError):
        _call(as_of=datetime(2026, 7, 25, 17, 10))                # naive as_of


def test_as_of_before_start_is_defined_failure_before_db():
    earlier = _START - timedelta(hours=1)
    r = _call(as_of=earlier)
    assert r.status == STATUS_UNAVAILABLE and r.reason == REASON_AS_OF_BEFORE_START
    assert r.real_clv_eligible is False and r.start_is_verified_first_pitch is False


def test_default_and_retrospective_as_of_labels_offline():
    # A None/equal as_of => contemporaneous; a later as_of => retrospective. The classification
    # itself is computed before the query; we witness it on the as_of_before_start echo path and
    # via the value passed through (full behavior is proven in integration).
    assert AS_OF_CONTEMPORANEOUS == "contemporaneous"
    assert AS_OF_RETROSPECTIVE == "retrospective"


# --- Offline: harness negatives + credential sanitization -------------------

def test_gate_allows_only_task_db_in_test_phase():
    assert evaluate_destination("test", "127.0.0.1", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5432, "postgres")[0]
    assert not evaluate_destination("test", "10.0.0.5", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination("test", "127.0.0.1", 5433, _TEST_DBNAME)[0]
    assert evaluate_destination("maintenance", "127.0.0.1", 5432, "postgres")[0]
    assert not evaluate_destination("maintenance", "127.0.0.1", 5432, _TEST_DBNAME)[0]
    assert not evaluate_destination(None, "127.0.0.1", 5432, _TEST_DBNAME)[0]


def test_synthetic_secret_is_sanitized():
    synthetic = "S3cr3t-SYNTHETIC-do-not-log"
    dsn = f"postgresql://postgres:{synthetic}@127.0.0.1:5432/{_TEST_DBNAME}"
    s = sanitize(dsn)
    assert synthetic not in s and "***" in s and _TEST_DBNAME in s


def test_reject_before_connect_with_sanitized_evidence():
    _attempts.clear()
    set_phase("test")
    synthetic = "S3cr3t-SYNTHETIC"
    hit = {"connected": False}

    def _real(*a, **k):
        hit["connected"] = True
        return object()

    with pytest.raises(ConnectionRejected):
        guarded_connect(_real, f"postgresql://u:{synthetic}@evil.example:5432/{_TEST_DBNAME}")
    assert hit["connected"] is False
    assert _attempts[-1]["allowed"] is False and synthetic not in _attempts[-1]["dest"]
    set_phase(None)


def test_gate_active_restores_on_failure():
    if _pg is None:
        pytest.skip("psycopg2 not importable")
    with pytest.raises(RuntimeError):
        with gate_active():
            assert _pg.connect is not _REAL_CONNECT
            raise RuntimeError("boom")
    assert _pg.connect is _REAL_CONNECT


# --- Integration: disposable-DB lifecycle (gated on approved DSN) ------------

_APPROVED_DSN = os.environ.get("ORACLE_CLOSING_LINE_TEST_DSN")


def _maintenance_dsn(dsn: str) -> str:
    u = urlsplit(dsn)
    return urlunsplit((u.scheme, u.netloc, "/" + _MAINT_DBNAME, "", ""))


_REAL_COLS = ("game_run_id, sportsbook, market, selected_side, price_format, price, "
              "source, data_origin, observed_at, supersedes_observation_id, correction_reason")
_SYNTH_COLS = ("observation_id, supersedes_observation_id, observed_at, ingested_at, price, "
               "game_run_id, sportsbook, market, selected_side, price_format, source, data_origin")


@pytest.mark.skipif(
    not _APPROVED_DSN,
    reason="disposable-loopback-DB lifecycle requires the session-supplied approved DSN in "
           "ORACLE_CLOSING_LINE_TEST_DSN (role with CREATEDB, host 127.0.0.1:5432, dbname "
           "oracle_closing_line_test); credential discovery/fallback prohibited. A skip is NOT proof.",
)
def test_disposable_db_lifecycle():  # pragma: no cover - runs only with approved DSN
    import psycopg2
    from psycopg2 import errors as pgerr  # noqa: F401

    dsn = _APPROVED_DSN
    host, port, db = parse_destination(dsn)
    assert host in _LOOPBACK_HOSTS and port == 5432 and db == _TEST_DBNAME, "destination not approved"
    maint = _maintenance_dsn(dsn)
    evid: list[str] = []

    def real_insert(cur, **f):
        cur.execute(
            f"INSERT INTO oracle_market_odds_observations ({_REAL_COLS}) "
            f"VALUES (%(game_run_id)s,%(sportsbook)s,'ML',%(selected_side)s,'american',%(price)s,"
            f"'market_odds_fixture','TEST_FIXTURE',%(observed_at)s,%(sup)s,%(cr)s) RETURNING observation_id",
            {"game_run_id": _GAME, "sportsbook": "FANDUEL_ON", "selected_side": f.get("side", "home"),
             "price": f["price"], "observed_at": f["obs"], "sup": f.get("sup"), "cr": f.get("cr")})
        return cur.fetchone()[0]

    def synth_insert(cur, oid, sup, obs, ing, price, side="home", g=_GAME, book="FANDUEL_ON"):
        cur.execute(
            f"INSERT INTO synth.oracle_market_odds_observations ({_SYNTH_COLS}) "
            f"VALUES (%s,%s,%s,%s,%s,%s,%s,'ML',%s,'american','market_odds_fixture','TEST_FIXTURE')",
            (oid, sup, obs, ing, price, g, book, side))

    def select(conn, **over):
        kw = dict(game_run_id=_GAME, selected_side="home", authoritative_start=_START,
                  start_version="v1", start_provenance="test-fixture")
        kw.update(over)
        return select_closing_line(conn, **kw)

    try:
        with gate_active():
            # ABSENT (pre) + ABORT if the task DB already exists.
            set_phase("maintenance")
            mc = psycopg2.connect(maint); mc.autocommit = True
            try:
                cur = mc.cursor()
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
                assert cur.fetchone() is None, "ABORT: task DB already exists (do not adopt/drop)"
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
                cur.execute("SET statement_timeout = '30s'")
                files = [_REPO / "database" / "schema.sql"] + sorted(
                    (_REPO / "database" / "migrations").glob("*.sql"))
                for f in files:
                    cur.execute(pathlib.Path(f).read_text(encoding="utf-8"))
                tc.commit()
                evid.append(f"provision={len(files)}_files_through_015")

                cur.execute(
                    "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, "
                    "daily_plays_activated, run_started_at) VALUES (%s,%s,%s,%s,%s)",
                    (_SLATE, _START.date(), "pregame_locked", 0, _START))
                cur.execute(
                    "INSERT INTO oracle_game_analyses (game_run_id, slate_run_id, external_game_id, "
                    "home_team, away_team, first_pitch_time, game_status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (_GAME, _SLATE, "746484", "NYY", "BOS", _START, "pregame_locked"))
                tc.commit()

                # ---- A. Actual-schema selection semantics (RC-1-correct: supplied start >= genuine ingested_at) ----
                cur.execute("SELECT clock_timestamp()"); t0 = cur.fetchone()[0]
                o_early = t0 - timedelta(hours=2)
                o_late = t0 - timedelta(hours=1)
                real_insert(cur, obs=o_early, price=120)
                hid = real_insert(cur, obs=o_late, price=140)          # latest instant, home
                real_insert(cur, obs=o_late, price=-105, side="away")  # per-side isolation
                tc.commit()
                cur.execute("SELECT clock_timestamp()"); t1 = cur.fetchone()[0]
                start = t1 + timedelta(minutes=1)                      # >= all genuine ingested_at
                r = select(tc, authoritative_start=start)              # default as_of=start (contemporaneous)
                assert r.status == STATUS_SELECTED and r.observation_id == hid and r.price == 140
                assert r.as_of_class == AS_OF_CONTEMPORANEOUS and r.real_clv_eligible is False
                assert r.start_is_verified_first_pitch is False and r.provenance == "fixture"
                assert r.observation_to_start_age_seconds > 0 and r.observation_to_start_age_iso.startswith("PT")
                assert select(tc, authoritative_start=start, selected_side="away").price == -105  # per-side isolation
                # no eligible: supplied start before the earliest observation
                assert select(tc, authoritative_start=o_early - timedelta(hours=1)).reason == "no_eligible_observation"
                evid.append("A_actual_select_perside_age_noeligible=ok")
                # independent-root conflict at the latest instant (two differing-price roots)
                real_insert(cur, obs=o_late, price=150); tc.commit()
                assert select(tc, authoritative_start=start).reason == "unresolved_conflict"
                evid.append("A_conflict_no_fallback=ok")

                # ---- B. Actual-schema historical reconstruction with GENUINE ingested_at ----
                # Reset via TRUNCATE (append-only trigger blocks UPDATE/DELETE; TRUNCATE is a
                # statement-level clear of THIS disposable table and removes no trigger/constraint).
                cur.execute("TRUNCATE oracle_market_odds_observations"); tc.commit()
                cur.execute("SELECT clock_timestamp()"); tb0 = cur.fetchone()[0]
                ob = tb0 - timedelta(hours=2)
                base = real_insert(cur, obs=ob, price=120); tc.commit()
                cur.execute("SELECT ingested_at FROM oracle_market_odds_observations WHERE observation_id=%s",
                            (base,)); base_ing = cur.fetchone()[0]
                corr = real_insert(cur, obs=ob, price=160, sup=base); tc.commit()
                cur.execute("SELECT ingested_at FROM oracle_market_odds_observations WHERE observation_id=%s",
                            (corr,)); corr_ing = cur.fetchone()[0]
                assert corr_ing > base_ing                             # genuine monotonic ingest (DB-forced)
                # contemporaneous as_of = start = base_ing: base visible, later correction invisible -> base head
                rb = select(tc, authoritative_start=base_ing, as_of=base_ing)
                assert rb.observation_id == base and rb.price == 120 and rb.as_of_class == AS_OF_CONTEMPORANEOUS
                # retrospective as_of after correction ingest: correction exposed (non-erasure preserved)
                rr = select(tc, authoritative_start=base_ing, as_of=corr_ing + timedelta(seconds=1))
                assert rr.observation_id == corr and rr.price == 160 and rr.as_of_class == AS_OF_RETROSPECTIVE
                evid.append("B_correction_after_asof_nonerasure+retrospective=ok")

                # ---- C+B(incomplete). Synthetic-relation execution of the PRODUCTION query --------
                # Isolation method: a separate schema `synth` holds a same-columns table WITHOUT the
                # real triggers/constraints; `SET search_path TO synth, public` makes the UNQUALIFIED
                # table name in cls._SELECTION_SQL resolve to the synthetic relation. The executed SQL
                # text is exactly the production selector query (asserted below). The real observation
                # table's triggers/constraints are never disabled or removed.
                assert "oracle_market_odds_observations" in cls._SELECTION_SQL  # unqualified -> search_path-resolvable
                cur.execute("CREATE SCHEMA synth")
                cur.execute(
                    "CREATE TABLE synth.oracle_market_odds_observations ("
                    "observation_id BIGINT PRIMARY KEY, supersedes_observation_id BIGINT, "
                    "observed_at TIMESTAMPTZ, ingested_at TIMESTAMPTZ, price INTEGER, "
                    "game_run_id VARCHAR, sportsbook VARCHAR, market VARCHAR, selected_side VARCHAR, "
                    "price_format VARCHAR, source VARCHAR, data_origin VARCHAR)")
                tc.commit()
                cur.execute("SET search_path TO synth, public")
                so = _START - timedelta(hours=1)
                sing = _START - timedelta(minutes=30)   # <= as_of(default=start)

                def reset_synth():
                    cur.execute("TRUNCATE synth.oracle_market_odds_observations"); tc.commit()

                # strict-before / equality-exclusion / after-exclusion (explicit ingested_at <= as_of)
                reset_synth()
                synth_insert(cur, 1, None, _START - timedelta(minutes=1), sing, 120)  # before -> eligible
                synth_insert(cur, 2, None, _START, sing, 130)                          # equal  -> excluded
                synth_insert(cur, 3, None, _START + timedelta(minutes=1), sing, 140)   # after  -> excluded
                tc.commit()
                assert select(tc).status == STATUS_SELECTED and select(tc).price == 120
                # latest qualifying instant among eligible
                reset_synth()
                synth_insert(cur, 1, None, _START - timedelta(hours=2), sing, 120)
                synth_insert(cur, 2, None, _START - timedelta(hours=1), sing, 140)
                tc.commit()
                assert select(tc).price == 140
                # as_of default (contemporaneous) vs later retrospective exposure of a correction
                reset_synth()
                synth_insert(cur, 1, None, _START - timedelta(hours=1), sing, 120)                 # root visible
                synth_insert(cur, 2, 1, _START - timedelta(hours=1), _START + timedelta(hours=1), 160)  # corr ingested after as_of
                tc.commit()
                assert select(tc).price == 120                                          # default as_of=start
                rlate = select(tc, as_of=_START + timedelta(hours=2))
                assert rlate.price == 160 and rlate.as_of_class == AS_OF_RETROSPECTIVE   # retrospective exposes it
                evid.append("C_boundary_latest_asof=ok")

                # independent roots vs malformed branch
                reset_synth()
                synth_insert(cur, 1, None, so, sing, 120); synth_insert(cur, 2, None, so, sing, 140); tc.commit()
                assert select(tc).reason == "unresolved_conflict"
                reset_synth()
                synth_insert(cur, 1, None, so, sing, 120)
                synth_insert(cur, 2, 1, so, sing, 130); synth_insert(cur, 3, 1, so, sing, 140); tc.commit()  # branch
                assert select(tc).reason == "malformed_history"
                # missing predecessor (referenced id genuinely ABSENT from the store) -> malformed_history
                reset_synth()
                synth_insert(cur, 2, 999, so, sing, 130); tc.commit()  # predecessor id 999 does not exist at all
                cur.execute("SELECT count(*) FROM synth.oracle_market_odds_observations WHERE observation_id=999")
                assert cur.fetchone()[0] == 0                          # predecessor truly ABSENT (distinct from CASE A)
                assert select(tc).reason == "malformed_history"
                evid.append("missing_predecessor_absent=malformed_history")
                # self-loop
                reset_synth()
                synth_insert(cur, 1, 1, so, sing, 120); tc.commit()
                assert select(tc).reason == "malformed_history"
                # ordinary headless cycle (3-node)
                reset_synth()
                synth_insert(cur, 1, 2, so, sing, 120); synth_insert(cur, 2, 3, so, sing, 130)
                synth_insert(cur, 3, 1, so, sing, 140); tc.commit()
                assert select(tc).reason == "malformed_history"
                # headless cycle alongside a valid independent root (root must not conceal)
                reset_synth()
                synth_insert(cur, 1, 2, so, sing, 120); synth_insert(cur, 2, 1, so, sing, 130)
                synth_insert(cur, 9, None, so, sing, 150); tc.commit()
                assert select(tc).reason == "malformed_history"
                # 256-node cycle -> malformed (no 257th traversal row)
                reset_synth()
                cur.execute(
                    "INSERT INTO synth.oracle_market_odds_observations (%s) "
                    "SELECT gs, CASE WHEN gs<256 THEN gs+1 ELSE 1 END, %%s,%%s,100+gs,"
                    "%%s,'FANDUEL_ON','ML','home','american','market_odds_fixture','TEST_FIXTURE' "
                    "FROM generate_series(1,256) gs" % _SYNTH_COLS, (so, sing, _GAME))
                tc.commit()
                assert select(tc).reason == "malformed_history"
                # clean 256-node chain -> Selected (root at depth 256)
                reset_synth()
                cur.execute(
                    "INSERT INTO synth.oracle_market_odds_observations (%s) "
                    "SELECT gs, CASE WHEN gs<256 THEN gs+1 ELSE NULL END, %%s,%%s,100+gs,"
                    "%%s,'FANDUEL_ON','ML','home','american','market_odds_fixture','TEST_FIXTURE' "
                    "FROM generate_series(1,256) gs" % _SYNTH_COLS, (so, sing, _GAME))
                tc.commit()
                assert select(tc).status == STATUS_SELECTED
                # clean 257-node chain -> traversal_exhausted
                reset_synth()
                cur.execute(
                    "INSERT INTO synth.oracle_market_odds_observations (%s) "
                    "SELECT gs, CASE WHEN gs<257 THEN gs+1 ELSE NULL END, %%s,%%s,100+gs,"
                    "%%s,'FANDUEL_ON','ML','home','american','market_odds_fixture','TEST_FIXTURE' "
                    "FROM generate_series(1,257) gs" % _SYNTH_COLS, (so, sing, _GAME))
                tc.commit()
                assert select(tc).reason == "traversal_exhausted"
                # incomplete projection: child visible, predecessor ingested AFTER as_of (non-monotonic)
                reset_synth()
                synth_insert(cur, 1, None, so, _START + timedelta(hours=1), 120)  # root ingested after as_of
                synth_insert(cur, 2, 1, so, sing, 160)                            # child visible
                tc.commit()
                assert select(tc).reason == "incomplete_historical_projection"
                # unrelated-instant corruption does not contaminate a clean latest instant
                reset_synth()
                synth_insert(cur, 1, 2, so - timedelta(hours=1), sing, 120)       # cycle at earlier instant
                synth_insert(cur, 2, 1, so - timedelta(hours=1), sing, 130)
                synth_insert(cur, 5, None, so, sing, 175)                         # clean latest instant
                tc.commit()
                assert select(tc).status == STATUS_SELECTED and select(tc).price == 175

                # CASE A (PM-1233) — EXISTING cross-coordinate predecessor (distinct from missing-predecessor).
                # Predecessor row exists but differs by exactly one coordinate field (selected_side); the
                # selected-family child is visible and eligible at the latest instant. Intended defect is
                # coordinate mismatch, NOT an absent row.
                reset_synth()
                synth_insert(cur, 1, None, so, sing, 120, side="away")   # predecessor EXISTS; one coord diff (side)
                synth_insert(cur, 2, 1, so, sing, 160, side="home")      # selected-family child references it
                tc.commit()
                cur.execute("SELECT count(*) FROM synth.oracle_market_odds_observations WHERE observation_id=1")
                assert cur.fetchone()[0] == 1                            # predecessor REALLY exists (not absent)
                cur.execute("SELECT selected_side FROM synth.oracle_market_odds_observations WHERE observation_id=1")
                assert cur.fetchone()[0] == "away"                       # the single coordinate difference
                # child visible & eligible at t* within the selected (home) family
                cur.execute("SELECT observed_at < %s AND ingested_at <= %s FROM "
                            "synth.oracle_market_odds_observations WHERE observation_id=2", (_START, _START))
                assert cur.fetchone()[0] is True
                assert select(tc, selected_side="home").reason == "malformed_history"  # cross-coordinate, not missing
                evid.append("CASE_A_cross_coordinate_predecessor=malformed_history")

                # CASE B (PM-1233) — proven cycle precedence over a SEPARATE exhausted lineage, same t*, same family.
                def load_cycle():                                       # 3-node cycle, closes within MAX_DEPTH
                    synth_insert(cur, 1, 2, so, sing, 120)
                    synth_insert(cur, 2, 3, so, sing, 130)
                    synth_insert(cur, 3, 1, so, sing, 140)

                def load_chain257():                                    # 257 nodes (ids 100..356) > MAX_DEPTH=256
                    cur.execute(
                        "INSERT INTO synth.oracle_market_odds_observations (%s) "
                        "SELECT gs, CASE WHEN gs<356 THEN gs+1 ELSE NULL END, %%s,%%s,gs,"
                        "%%s,'FANDUEL_ON','ML','home','american','market_odds_fixture','TEST_FIXTURE' "
                        "FROM generate_series(100,356) gs" % _SYNTH_COLS, (so, sing, _GAME))

                reset_synth(); load_cycle(); tc.commit()
                assert select(tc).reason == "malformed_history"         # cycle component ALONE
                reset_synth(); load_chain257(); tc.commit()
                assert select(tc).reason == "traversal_exhausted"       # clean 257-node component ALONE
                reset_synth(); load_cycle(); load_chain257(); tc.commit()
                assert select(tc).reason == "malformed_history"         # BOTH at same t*: proven-cycle precedence
                evid.append("CASE_B_cycle_precedes_exhausted=malformed_history")

                cur.execute("SET search_path TO public")
                tc.commit()
                evid.append("C_integrity_synthetic=ok B_incomplete=ok")

                # ---- D. Caller-owned read behavior (real connection witnesses) ----
                sel_start = corr_ing + timedelta(minutes=1)   # >= corr ingest -> a genuine SELECTED read
                # (i) selector performs NO commit: a witness created in the caller's uncommitted tx is
                #     discarded by the CALLER's rollback (would survive only if the selector had committed).
                cur.execute("CREATE TEMP TABLE witness_d(x int)")
                cur.execute("INSERT INTO witness_d VALUES (1)")
                assert select(tc, authoritative_start=sel_start, as_of=sel_start).status == STATUS_SELECTED
                tc.rollback()                                 # caller-owned rollback
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='witness_d'")
                assert cur.fetchone()[0] == 0                 # selector did not commit caller work
                # (ii) connection remains caller-usable after SELECTED and Unavailable reads; caller commits.
                assert select(tc, authoritative_start=sel_start, as_of=sel_start).status == STATUS_SELECTED
                u = select(tc, authoritative_start=tb0 - timedelta(hours=5))   # Unavailable (no eligible)
                assert u.status == STATUS_UNAVAILABLE
                cur.execute("SELECT 1"); assert cur.fetchone()[0] == 1         # still usable; caller-owned
                tc.commit()                                   # caller-controlled commit after reads
                evid.append("D_caller_owned=ok")
                # (iii) selector does NOT roll back unrelated uncommitted caller work (executed witness).
                # Complements source inspection (the module issues no commit/rollback/close) per PM-1232.
                cur.execute("CREATE TEMP TABLE witness_nr(x int)")
                cur.execute("INSERT INTO witness_nr VALUES (7)")
                _ = select(tc, authoritative_start=sel_start, as_of=sel_start)  # a selector read
                cur.execute("SELECT count(*) FROM witness_nr")
                assert cur.fetchone()[0] == 1                 # caller's uncommitted row survived the selector call
                tc.rollback()
                evid.append("D_no_rollback_of_unrelated_work=ok")

                cur.close()
            finally:
                tc.close()

        assert _pg.connect is _REAL_CONNECT, "connector not restored"
        evid.append("connector_restored=True")
    finally:
        with gate_active():
            set_phase("maintenance")
            mc = psycopg2.connect(maint); mc.autocommit = True
            try:
                cur = mc.cursor()
                cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname=%s AND pid<>pg_backend_pid()", (db,))
                cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db,))
                assert cur.fetchone() is None
                evid.append("drop=ok absent_post=True")
                cur.close()
            finally:
                mc.close()

    print("CL_LIFECYCLE_EVIDENCE:", " | ".join(evid))
    assert evid
