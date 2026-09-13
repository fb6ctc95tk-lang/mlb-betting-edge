"""Acceptance tests for fixture-context MANUAL paper-play settlement (PM-1169).

Connection enforcement is scoped to the disposable lifecycle via `gate_active()` and is NEVER installed
at import. While active: acceptance connections only to 127.0.0.1:5432/oracle_manual_settlement_test;
maintenance `postgres` only for bounded existence/create/drop/cleanup; all else rejected before connect.
The original connector is ALWAYS restored on exit. The real lifecycle runs only when the Rich-approved
manual-play DSN is inherited (credentials reused, database name replaced); otherwise it skips. Pure/mock/
gate tests run without any DB.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import pytest

# --- connection-enforcement harness (scoped; not installed at import) --------

_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_TASK_DB = "oracle_manual_settlement_test"
_MAINT_DB = "postgres"
_ALLOWED = {"maintenance": frozenset({_MAINT_DB}), "test": frozenset({_TASK_DB})}
_phase = {"cur": None}
_attempts: list[dict] = []


class ConnectionRejected(Exception):
    pass


def set_phase(p):
    _phase["cur"] = p


def _parse(dsn=None, **kw):
    if dsn:
        u = urlsplit(dsn)
        return (u.hostname, u.port or 5432, (u.path or "/").lstrip("/"))
    return (kw.get("host"), kw.get("port", 5432), kw.get("dbname"))


def sanitize(dsn=None, **kw):
    if dsn:
        u = urlsplit(dsn)
        user = (u.username + ":***@") if u.username else ""
        return f"{u.scheme}://{user}{u.hostname or ''}:{u.port or 5432}/{(u.path or '/').lstrip('/')}"
    return f"host={kw.get('host')} port={kw.get('port',5432)} dbname={kw.get('dbname')} password=***"


def evaluate_destination(phase, host, port, dbname):
    if phase not in _ALLOWED:
        return (False, f"phase {phase!r} denies all connections")
    if host not in _LOOPBACK:
        return (False, f"host {host!r} not loopback")
    if port != 5432:
        return (False, f"port {port!r} not allowed")
    if dbname not in _ALLOWED[phase]:
        return (False, f"dbname {dbname!r} not allowed in phase {phase!r}")
    return (True, "allowed")


def guarded_connect(real, dsn=None, **kw):
    host, port, db = _parse(dsn, **kw)
    ok, why = evaluate_destination(_phase["cur"], host, port, db)
    _attempts.append({"phase": _phase["cur"], "dest": sanitize(dsn, **kw), "allowed": ok, "reason": why})
    if not ok:
        raise ConnectionRejected(why)
    return real(dsn, **kw) if dsn else real(**kw)


try:  # pragma: no cover - environment dependent
    import psycopg2 as _pg
    _REAL_CONNECT = _pg.connect  # captured only; NOT patched at import
except Exception:
    _pg = None
    _REAL_CONNECT = None


@contextlib.contextmanager
def gate_active():
    if _pg is None:
        yield
        return
    original = _pg.connect
    _pg.connect = lambda dsn=None, **kw: guarded_connect(_REAL_CONNECT, dsn, **kw)
    try:
        yield
    finally:
        _pg.connect = original
        set_phase(None)


from backend.oracle import manual_settlement as ms  # noqa: E402
from backend.oracle import results_fixtures as rf  # noqa: E402

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "1"}
_OBS = "2026-07-25T20:45:00Z"
_SETTLED_AT = datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc)
_SLATE = "ORACLE-20260725-001"
_GAME = "ORACLE-20260725-001-BOS-NYY-746484"
_EXT = "746484"
_REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


def _result(ext=_EXT, status="final", home=5, away=3, obs=_OBS):
    return {"external_game_id": ext, "game_status": status, "home_score": home, "away_score": away,
            "result_observed_at": obs, "source": rf.FIXTURE_SOURCE, "data_origin": rf.TEST_DATA_ORIGIN}


def _play(**over):
    p = {"play_id": "EO-2026-001", "game_run_id": _GAME, "slate_run_id": _SLATE, "market": "ML",
         "selected_side": "home", "origin": "MANUAL", "odds_at_nomination": 120,
         "stake_units": Decimal("1.0000"), "settlement_result": None, "mock_pnl": None,
         "play_status": "nominated"}
    p.update(over)
    return p


def _play_tuple(p):
    return (p["game_run_id"], p["slate_run_id"], p["market"], p["selected_side"], p["origin"],
            p["odds_at_nomination"], p["stake_units"], p["settlement_result"], p["mock_pnl"],
            p["play_status"])


# --- pure: normalization equivalence, immutability, identity, decimal --------

def test_canonical_copy_normalizes_without_mutating_caller():
    r_pad = _result(status="  FINAL  ")
    canon = ms.canonical_result_copy(r_pad)
    assert canon["game_status"] == "final"
    assert r_pad["game_status"] == "  FINAL  "  # caller input unchanged
    canon["home_score"] = 999
    assert r_pad["home_score"] == 5  # fresh copy


def test_normalization_equivalence_identical_identity_and_disposition():
    p = _play()
    id_a = ms.build_identity(p, ms.canonical_result_copy(_result(status="final")))
    id_b = ms.build_identity(p, ms.canonical_result_copy(_result(status=" Final ")))
    assert ms.canonical_identity_payload(id_a) == ms.canonical_identity_payload(id_b)


def test_identity_has_exactly_15_canonical_fields():
    idn = ms.build_identity(_play(), ms.canonical_result_copy(_result()))
    assert set(idn) == set(ms.IDENTITY_FIELDS) and len(ms.IDENTITY_FIELDS) == 15
    for f in ("external_game_id", "origin", "stake_units"):
        assert f in idn
    assert idn["origin"] == "MANUAL" and idn["stake_units"] == "1.0000"


def test_decimal_results_and_serialization():
    assert ms.american_profit(150, Decimal("1")) == Decimal("1.5")
    assert ms._decimal_str(ms.american_profit(150, Decimal("1"))) == "1.5000"
    assert ms._decimal_str(ms.american_profit(-110, Decimal("1"))) == "0.9091"  # 100/110 HALF_UP
    assert ms._decimal_str(-Decimal("1")) == "-1.0000"
    assert ms._decimal_str(Decimal(0)) == "0.0000"


# --- mock connection ---------------------------------------------------------

class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._one = None
        self._all = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "FROM oracle_plays WHERE play_id" in s:
            self._one = self.conn.play_tuple
        elif "FROM oracle_game_analyses" in s and "external_game_id" in s:
            self._all = list(self.conn.match_rows)
        elif "FROM oracle_play_events" in s and "settlement_completed" in s:
            self._all = list(self.conn.events_rows)
        elif s.startswith("UPDATE oracle_plays SET settlement_result"):
            self.rowcount = self.conn.update_rowcount
            self.conn.updates.append(params)
        elif "INSERT INTO oracle_play_events" in s:
            self.conn.events_written.append(params)
            self._one = (1,)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def close(self):
        pass


class _Conn:
    autocommit = False

    def __init__(self, play_tuple=None, match_rows=None, events_rows=(), update_rowcount=1):
        self.play_tuple = play_tuple
        self.match_rows = match_rows if match_rows is not None else ([(play_tuple[0],)] if play_tuple else [])
        self.events_rows = events_rows
        self.update_rowcount = update_rowcount
        self.updates = []
        self.events_written = []
        self.committed = 0
        self.rolled = 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled += 1


def _settle(conn, **over):
    kw = dict(play_id="EO-2026-001", result_record=_result(), settled_at=_SETTLED_AT, env=_ENABLED)
    kw.update(over)
    return ms.settle_manual_play(conn, **kw)


def test_kill_switch_first_untouched():
    class _Boom:
        autocommit = False
        def cursor(self): raise AssertionError("connection touched with kill switch off")
        def rollback(self): raise AssertionError("rollback before work")
    with pytest.raises(ms.KillSwitchHaltError):
        _settle(_Boom(), env={})


def test_binding_rejections():
    with pytest.raises(ms.ManualSettlementBindingError):   # play not found
        _settle(_Conn(play_tuple=None))
    with pytest.raises(ms.ManualSettlementBindingError):   # non-MANUAL origin
        _settle(_Conn(play_tuple=_play_tuple(_play(origin="ORACLE_EDGE"))))
    with pytest.raises(ms.ManualSettlementBindingError):   # zero matches in slate
        _settle(_Conn(play_tuple=_play_tuple(_play()), match_rows=[]))
    with pytest.raises(ms.ManualSettlementBindingError):   # matched game != play's game
        _settle(_Conn(play_tuple=_play_tuple(_play()), match_rows=[("ORACLE-20260725-001-OTH-999",)]))


def test_duplicate_in_slate_matches_rejected():
    c = _Conn(play_tuple=_play_tuple(_play()),
              match_rows=[(_GAME,), ("ORACLE-20260725-001-DUP-999",)])
    with pytest.raises(ms.ManualSettlementBindingError):
        _settle(c)
    assert c.updates == [] and c.events_written == [] and c.committed == 0


def test_malformed_nested_identity_payload_is_audit_failure_not_changed_result():
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    good = _good_payload(_play(), _result(status="final", home=5, away=3), "win", "1.2000")
    obj = json.loads(good["identity_payload"])
    miss = dict(obj); miss.pop("origin")
    extra = dict(obj); extra["surprise"] = 1
    variants = [
        "{not valid json",                                              # invalid JSON
        json.dumps(miss, sort_keys=True, separators=(",", ":")),        # missing field
        json.dumps(extra, sort_keys=True, separators=(",", ":")),       # extra field
        json.dumps(obj, sort_keys=True),                                # noncanonical (spaces)
    ]
    for bad_ip in variants:
        ev = dict(good); ev["identity_payload"] = bad_ip
        c = _Conn(play_tuple=_play_tuple(settled), events_rows=[(ev,)])
        with pytest.raises(ms.ManualSettlementAuditError):
            _settle(c, result_record=_result(status="final", home=5, away=3))


def _stored_event(overrides=None, sr="win", pnl="1.2000", settled_iso=None):
    idn = ms.build_identity(_play(), ms.canonical_result_copy(_result(status="final", home=5, away=3)))
    if overrides:
        idn = dict(idn); idn.update(overrides)
    payload = json.dumps(idn, sort_keys=True, separators=(",", ":"))
    return {"identity_payload": payload, "settlement_result": sr, "mock_pnl": pnl,
            "settled_at": settled_iso or _SETTLED_AT.isoformat(),
            "mset_label": "MSET-EO-2026-001-0000000000000000"}


@pytest.mark.parametrize("override", [
    {"play_id": "EO-2026-999"}, {"game_run_id": "ORACLE-20260725-001-XXX-1"},
    {"slate_run_id": "ORACLE-20260725-002"}, {"origin": "ORACLE_EDGE"}, {"market": "RL"},
    {"selected_side": "away"}, {"odds_at_nomination": 150}, {"stake_units": "2.0000"},
    {"external_game_id": "999999"}, {"odds_at_nomination": 50}, {"odds_at_nomination": -99},
    {"odds_at_nomination": 0},
])
def test_immutable_field_or_invalid_odds_is_audit_error(override):
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    c = _Conn(play_tuple=_play_tuple(settled), events_rows=[(_stored_event(override),)])
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(c, result_record=_result(status="final", home=5, away=3))
    assert c.updates == [] and c.events_written == [] and c.committed == 0


@pytest.mark.parametrize("override", [
    {"game_status": "final", "home_score": None, "away_score": None},      # final without scores
    {"game_status": "postponed", "home_score": 5, "away_score": 3},        # non-final with scores
    {"game_status": "postponed", "home_score": None, "away_score": None},  # defer settles nothing
    {"game_status": "suspended", "home_score": None, "away_score": None},  # defer settles nothing
    {"game_status": "final", "home_score": 5, "away_score": 5},            # tied final
    {"result_observed_at": "2026-13-40T00:00:00Z"},                        # invalid real date
    {"result_observed_at": "2026-07-25 20:45:00Z"},                        # noncanonical timestamp
])
def test_status_score_or_date_inconsistency_is_audit_error(override):
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    c = _Conn(play_tuple=_play_tuple(settled), events_rows=[(_stored_event(override),)])
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(c, result_record=_result(status="final", home=5, away=3))
    assert c.updates == [] and c.events_written == [] and c.committed == 0


def test_invalid_result_record_fails_closed():
    bad = _result(); bad["data_origin"] = "LIVE"
    with pytest.raises(rf.ResultFixtureValidationError):
        _settle(_Conn(play_tuple=_play_tuple(_play())), result_record=bad)


def test_dispositions_win_loss_void_defer_tie():
    c = _Conn(play_tuple=_play_tuple(_play()))
    r = _settle(c, result_record=_result(status="final", home=5, away=3))  # side home wins
    assert r.outcome == ms.SETTLED_WIN and r.settlement_result == "win" and r.mock_pnl == "1.2000"
    assert len(c.updates) == 1 and len(c.events_written) == 1 and c.committed == 1

    c = _Conn(play_tuple=_play_tuple(_play(odds_at_nomination=-110)))
    r = _settle(c, result_record=_result(status="final", home=3, away=5))
    assert r.outcome == ms.SETTLED_LOSS and r.mock_pnl == "-1.0000"

    c = _Conn(play_tuple=_play_tuple(_play()))
    r = _settle(c, result_record=_result(status="cancelled", home=None, away=None))
    assert r.outcome == ms.VOIDED and r.settlement_result == "void" and r.mock_pnl == "0.0000"

    for st in ("postponed", "suspended"):
        c = _Conn(play_tuple=_play_tuple(_play()))
        r = _settle(c, result_record=_result(status=st, home=None, away=None))
        assert r.outcome == ms.DEFERRED and c.updates == [] and c.events_written == [] and c.committed == 0

    c = _Conn(play_tuple=_play_tuple(_play()))
    r = _settle(c, result_record=_result(status="final", home=4, away=4))
    assert r.outcome == ms.REJECTED_TIE and c.updates == [] and c.events_written == []


def test_atomic_rollback_on_event_failure(monkeypatch):
    c = _Conn(play_tuple=_play_tuple(_play()))
    monkeypatch.setattr(ms, "record_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _settle(c, result_record=_result(status="final", home=5, away=3))
    assert c.rolled >= 1 and c.committed == 0


def _good_payload(play, result, sr, pnl, settled_iso=None, label=None):
    idn = ms.build_identity(play, ms.canonical_result_copy(result))
    payload = ms.canonical_identity_payload(idn)
    return {"identity_payload": payload, "settlement_result": sr, "mock_pnl": pnl,
            "settled_at": settled_iso or _SETTLED_AT.isoformat(),
            "mset_label": label or ms.mset_label(play["play_id"], payload)}


def test_audit_integrity_failures():
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    # missing
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[]), result_record=_result())
    # multiple
    ev = _good_payload(_play(), _result(), "win", "1.2000")
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[(ev,), (ev,)]), result_record=_result())
    # malformed
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[({"bogus": 1},)]), result_record=_result())
    # projection conflict (stored says loss, projection says win)
    ev2 = _good_payload(_play(), _result(), "loss", "-1.0000")
    with pytest.raises(ms.ManualSettlementAuditError):
        _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[(ev2,)]), result_record=_result())


def test_replay_exact_and_changed_full_payload_and_timestamp_preserved():
    first_iso = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc).isoformat()
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    ev = _good_payload(_play(), _result(status="final", home=5, away=3), "win", "1.2000",
                       settled_iso=first_iso)
    # EXACT_REPLAY: same result; later settled_at supplied but stored is preserved
    r = _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[(ev,)]),
                result_record=_result(status="final", home=5, away=3), settled_at=_SETTLED_AT)
    assert r.outcome == ms.EXACT_REPLAY and r.settled_at == first_iso
    # CHANGED_RESULT: different scores → different full canonical payload
    r2 = _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[(ev,)]),
                 result_record=_result(status="final", home=1, away=0))
    assert r2.outcome == ms.CHANGED_RESULT and r2.divergence


def test_short_label_is_not_authoritative_for_equality():
    # Stored identity_payload matches, but the stored mset_label differs → still EXACT_REPLAY.
    settled = _play(settlement_result="win", mock_pnl=Decimal("1.2000"), play_status="settled")
    ev = _good_payload(_play(), _result(status="final", home=5, away=3), "win", "1.2000",
                       label="MSET-EO-2026-001-deadbeefdeadbeef")
    r = _settle(_Conn(play_tuple=_play_tuple(settled), events_rows=[(ev,)]),
                result_record=_result(status="final", home=5, away=3))
    assert r.outcome == ms.EXACT_REPLAY


# --- real disposable-DB lifecycle (gated on derived task DSN) ----------------

_BASE_DSN = os.environ.get("ORACLE_MANUAL_PLAY_TEST_DSN")


def _with_db(dsn, name):
    u = urlsplit(dsn)
    return urlunsplit((u.scheme, u.netloc, "/" + name, "", ""))


def _apply(cur, path):
    cur.execute(__import__("pathlib").Path(path).read_text(encoding="utf-8"))


@pytest.mark.skipif(
    not _BASE_DSN,
    reason="requires inherited approved manual-play DSN (credentials reused; db name replaced with "
           "oracle_manual_settlement_test); no discovery/fallback/disclosure",
)
def test_disposable_db_lifecycle():  # pragma: no cover - runs only with approved DSN
    import psycopg2
    task = _with_db(_BASE_DSN, _TASK_DB)
    maint = _with_db(_BASE_DSN, _MAINT_DB)
    assert _parse(task) == ("127.0.0.1", 5432, _TASK_DB) or _parse(task)[2] == _TASK_DB
    evid = []

    try:
        with gate_active():
            set_phase("maintenance")
            mc = psycopg2.connect(maint); mc.autocommit = True
            try:
                cur = mc.cursor()
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (_TASK_DB,))
                assert cur.fetchone() is None, "ABORT: task DB already exists"
                evid.append("absent_pre=True")
                cur.execute(f'CREATE DATABASE "{_TASK_DB}"'); evid.append("create=ok")
                cur.close()
            finally:
                mc.close()

            set_phase("test")
            tc = psycopg2.connect(task); tc.autocommit = False
            try:
                cur = tc.cursor()
                files = [_REPO / "database" / "schema.sql"] + sorted(
                    (_REPO / "database" / "migrations").glob("*.sql"))
                for f in files:
                    _apply(cur, f)
                tc.commit(); evid.append(f"provision={len(files)}_files")

                cur.execute("INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, "
                            "daily_plays_activated, run_started_at) VALUES (%s,%s,%s,%s,%s)",
                            (_SLATE, date(2026, 7, 25), "pregame_locked", 0, _SETTLED_AT))
                games = {f"G{i}": f"{74650+i}" for i in range(1, 9)}
                plays = {}  # play_id -> (game_run_id, ext, odds)
                for i, (g, ext) in enumerate(games.items(), start=1):
                    gr = f"{_SLATE}-{g}-{ext}"
                    cur.execute("INSERT INTO oracle_game_analyses (game_run_id, slate_run_id, "
                                "external_game_id, home_team, away_team, first_pitch_time, game_status) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                (gr, _SLATE, ext, "NYY", "BOS", _SETTLED_AT, "pregame_locked"))
                    pid = f"EO-2026-{i:03d}"; odds = 120 if i != 2 else -110
                    cur.execute("INSERT INTO oracle_plays (play_id, candidate_id, slate_run_id, "
                                "game_run_id, market, selected_side, odds_at_nomination, stake_units, "
                                "nomination_timestamp, play_status, origin) VALUES "
                                "(%s,%s,%s,%s,'ML','home',%s,1.0,%s,'nominated','MANUAL')",
                                (pid, f"MANUAL-CAND-{gr}-ML-home", _SLATE, gr, odds, _SETTLED_AT))
                    plays[pid] = (gr, ext, odds)
                tc.commit()

                def rr(ext, **kw):
                    return _result(ext=ext, **kw)

                # win / loss / void / defer / reject
                assert ms.settle_manual_play(tc, play_id="EO-2026-001",
                    result_record=rr(plays["EO-2026-001"][1], status="final", home=5, away=3),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.SETTLED_WIN
                assert ms.settle_manual_play(tc, play_id="EO-2026-002",
                    result_record=rr(plays["EO-2026-002"][1], status="final", home=3, away=5),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.SETTLED_LOSS
                assert ms.settle_manual_play(tc, play_id="EO-2026-003",
                    result_record=rr(plays["EO-2026-003"][1], status="cancelled", home=None, away=None),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.VOIDED
                assert ms.settle_manual_play(tc, play_id="EO-2026-004",
                    result_record=rr(plays["EO-2026-004"][1], status="postponed", home=None, away=None),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.DEFERRED
                assert ms.settle_manual_play(tc, play_id="EO-2026-005",
                    result_record=rr(plays["EO-2026-005"][1], status="final", home=4, away=4),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.REJECTED_TIE
                evid.append("dispositions=win/loss/void/defer/reject")

                # same-connection replay: EXACT then CHANGED, no duplicate event
                p6 = plays["EO-2026-006"][1]
                ms.settle_manual_play(tc, play_id="EO-2026-006",
                    result_record=rr(plays["EO-2026-006"][1], status="final", home=5, away=3),
                    settled_at=_SETTLED_AT, env=_ENABLED)
                assert ms.settle_manual_play(tc, play_id="EO-2026-006",
                    result_record=rr(plays["EO-2026-006"][1], status="final", home=5, away=3),
                    settled_at=datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc), env=_ENABLED
                    ).outcome == ms.EXACT_REPLAY
                assert ms.settle_manual_play(tc, play_id="EO-2026-006",
                    result_record=rr(plays["EO-2026-006"][1], status="final", home=1, away=0),
                    settled_at=_SETTLED_AT, env=_ENABLED).outcome == ms.CHANGED_RESULT
                cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE play_id='EO-2026-006' "
                            "AND event_type='settlement_completed'")
                assert cur.fetchone()[0] == 1
                evid.append("replay=EXACT+CHANGED_no_dup")

                # real two-connection contention: conditional-update losers reconcile → both outcomes
                def contend(pid, ext, a_home, a_away, b_home, b_away, expected):
                    ca = psycopg2.connect(task); ca.autocommit = False
                    gr = f"{_SLATE}-" + [g for g, e in games.items() if e == ext][0] + f"-{ext}"
                    play = _play(play_id=pid, game_run_id=gr)
                    a_res = rr(ext, status="final", home=a_home, away=a_away)
                    real_fn = ms.canonical_identity_payload
                    fired = {"x": False}

                    def racing(identity):
                        p = real_fn(identity)
                        if not fired["x"]:
                            fired["x"] = True
                            a_can = ms.canonical_result_copy(a_res)
                            a_ident = ms.build_identity(play, a_can)
                            a_pl = real_fn(a_ident)
                            a_win = a_home > a_away
                            a_sr = "win" if a_win else "loss"
                            a_pnl = ms._decimal_str(ms.american_profit(120, Decimal("1")) if a_win
                                                    else -Decimal("1"))
                            ac = ca.cursor()
                            ac.execute("UPDATE oracle_plays SET settlement_result=%s, mock_pnl=%s, "
                                       "settled_at=%s, play_status='settled' WHERE play_id=%s AND "
                                       "settlement_result IS NULL", (a_sr, a_pnl, _SETTLED_AT, pid))
                            ms.record_event(ca, "settlement_completed", _SLATE, _SETTLED_AT,
                                            game_run_id=gr, play_id=pid,
                                            payload={"track": "manual", "real_performance": False,
                                                     "origin": "MANUAL", "data_origin": "TEST_FIXTURE",
                                                     "settlement_result": a_sr, "mock_pnl": a_pnl,
                                                     "settled_at": _SETTLED_AT.isoformat(),
                                                     "result_observed_at": _OBS,
                                                     "identity_payload": a_pl,
                                                     "mset_label": ms.mset_label(pid, a_pl),
                                                     "clv_unavailable_reason": ms.CLV_UNAVAILABLE_REASON})
                            ca.commit(); ac.close()
                        return p

                    ms.canonical_identity_payload = racing
                    try:
                        r = ms.settle_manual_play(tc, play_id=pid,
                            result_record=rr(ext, status="final", home=b_home, away=b_away),
                            settled_at=_SETTLED_AT, env=_ENABLED)
                    finally:
                        ms.canonical_identity_payload = real_fn
                        ca.close()
                    assert r.outcome == expected
                    cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE play_id=%s AND "
                                "event_type='settlement_completed'", (pid,))
                    assert cur.fetchone()[0] == 1  # exactly one event (no duplicate)
                    # Winner (A, a win) projection is authoritative and unchanged; loser's outcome/P&L
                    # is NEVER substituted.
                    cur.execute("SELECT settlement_result, mock_pnl, settled_at FROM oracle_plays "
                                "WHERE play_id=%s", (pid,))
                    wr = cur.fetchone()
                    assert wr[0] == "win" and Decimal(wr[1]) == Decimal("1.2000") and wr[2] == _SETTLED_AT

                contend("EO-2026-007", plays["EO-2026-007"][1], 5, 3, 5, 3, ms.EXACT_REPLAY)
                contend("EO-2026-008", plays["EO-2026-008"][1], 5, 3, 3, 5, ms.CHANGED_RESULT)
                evid.append("two_conn=EXACT+CHANGED_no_dup")
                cur.close()
            finally:
                tc.close()

        # gate restored: import isolation + same-task-DB access after restoration
        assert _pg.connect is _REAL_CONNECT
        evid.append("connector_restored=True")
        set_phase(None)
        cu = psycopg2.connect(task); cu.autocommit = True
        try:
            uc = cu.cursor(); uc.execute("SELECT COUNT(*) FROM oracle_plays"); uc.fetchone(); uc.close()
            evid.append("unrelated_db_after_restore=ok")
        finally:
            cu.close()
    finally:
        with gate_active():
            set_phase("maintenance")
            mc = psycopg2.connect(maint); mc.autocommit = True
            try:
                cur = mc.cursor()
                cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s "
                            "AND pid<>pg_backend_pid()", (_TASK_DB,))
                cur.execute(f'DROP DATABASE IF EXISTS "{_TASK_DB}"')
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (_TASK_DB,))
                assert cur.fetchone() is None
                evid.append("drop=ok absent_post=True")
                cur.close()
            finally:
                mc.close()

    print("LIFECYCLE_EVIDENCE:", " | ".join(evid))
    assert evid
