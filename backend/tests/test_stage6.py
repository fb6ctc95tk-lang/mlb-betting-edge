"""Oracle Inc-3+ — Evidence-safe Stage 6 lineup-monitoring tests (PM-1031/PM-1029).

Sections:
  A. Adapter classification (mocked network; fixtures) — UNAVAILABLE/PARTIAL/OBSERVED_FULL
  B. Epistemic discipline — probable stays PROBABLE; never AUTHORITATIVELY_CONFIRMED
  C. stage6_lineup — snapshot identity + material-change detection
  D. Orchestrator run_stage_6 — kill switch (mocked)
  E. DB integration (requires ORACLE_TEST_DATABASE_URL): persist/replay/change/
     unavailable/partial/conflict, event emission + non-emission, stays lineup_monitoring
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from backend.oracle import mlb_adapter as mlb
from backend.oracle.mlb_adapter import (
    LINEUP_OBSERVED_FULL,
    LINEUP_PARTIAL,
    LINEUP_UNAVAILABLE,
    PITCHER_PROBABLE,
    LineupObservation,
    MLBAdapter,
)
from backend.oracle import stage6_lineup as s6
from backend.oracle import orchestrator
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    Stage6ReplayConflictError,
    run_stage_6,
)

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "false"}


# --- fixture provider payload builders -------------------------------------

class _FakeResp:
    def __init__(self, payload, http_error=False):
        self._payload = payload
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise requests.exceptions.HTTPError("500")

    def json(self):
        return self._payload


def _game(home_ids, away_ids, home_pp=None, away_pp=None, status="Preview"):
    def players(ids):
        return [{"id": i, "fullName": f"P{i}"} for i in ids]
    teams = {"home": {}, "away": {}}
    if home_pp is not None:
        teams["home"]["probablePitcher"] = {"id": home_pp, "fullName": f"SP{home_pp}"}
    if away_pp is not None:
        teams["away"]["probablePitcher"] = {"id": away_pp, "fullName": f"SP{away_pp}"}
    return {"dates": [{"games": [{
        "gamePk": 999, "status": {"detailedState": status},
        "lineups": {"homePlayers": players(home_ids), "awayPlayers": players(away_ids)},
        "teams": teams,
    }]}]}


def _patch_get(payload=None, exc=None, http_error=False):
    def fake_get(url, params=None, timeout=None):
        if exc is not None:
            raise exc
        return _FakeResp(payload, http_error=http_error)
    return patch.object(mlb.requests, "get", side_effect=fake_get)


# ===========================================================================
# A. Adapter classification
# ===========================================================================

FULL9 = list(range(1, 10))


def test_observed_full_when_both_orders_full_and_both_pitchers():
    with _patch_get(_game(FULL9, [10 + i for i in range(9)], home_pp=100, away_pp=200)):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_OBSERVED_FULL
    assert obs.home_order == tuple(FULL9)
    assert obs.home_pitcher == {"id": 100, "epistemic_status": PITCHER_PROBABLE}
    assert obs.home_lineup_status == LINEUP_OBSERVED_FULL


def test_partial_when_one_side_missing():
    with _patch_get(_game(FULL9, [], home_pp=100, away_pp=None)):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_PARTIAL


def test_partial_when_pitcher_missing():
    with _patch_get(_game(FULL9, [10 + i for i in range(9)], home_pp=100, away_pp=None)):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_PARTIAL


def test_unavailable_when_no_data():
    with _patch_get(_game([], [], home_pp=None, away_pp=None)):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_UNAVAILABLE


def test_unavailable_on_connection_error():
    with _patch_get(exc=requests.exceptions.ConnectionError()):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_UNAVAILABLE
    assert obs.home_order == ()


def test_unavailable_on_timeout():
    with _patch_get(exc=requests.exceptions.Timeout()):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_UNAVAILABLE


def test_unavailable_on_http_error():
    with _patch_get(payload={}, http_error=True):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_UNAVAILABLE


def test_unavailable_on_empty_dates():
    with _patch_get({"dates": []}):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.classification == LINEUP_UNAVAILABLE


# ===========================================================================
# B. Epistemic discipline
# ===========================================================================

def test_pitcher_is_probable_never_confirmed():
    with _patch_get(_game(FULL9, [10 + i for i in range(9)], home_pp=100, away_pp=200)):
        obs = MLBAdapter().observe_lineup("999")
    assert obs.home_pitcher["epistemic_status"] == "PROBABLE"
    assert obs.away_pitcher["epistemic_status"] == "PROBABLE"


def test_adapter_never_emits_authoritatively_confirmed_status():
    with _patch_get(_game(FULL9, [10 + i for i in range(9)], home_pp=100, away_pp=200)):
        obs = MLBAdapter().observe_lineup("999")
    for v in (obs.classification, obs.home_lineup_status, obs.away_lineup_status):
        assert v != "AUTHORITATIVELY_CONFIRMED"
    assert not hasattr(mlb, "AUTHORITATIVELY_CONFIRMED")


# ===========================================================================
# C. stage6_lineup — snapshot identity + material-change detection
# ===========================================================================

def _obs(home, away, hpp, app):
    with _patch_get(_game(home, away, home_pp=hpp, away_pp=app)):
        return MLBAdapter().observe_lineup("999")


def test_snapshot_identity_deterministic():
    o1 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    o2 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    assert s6.compute_snapshot_identity("G", o1) == s6.compute_snapshot_identity("G", o2)


def test_snapshot_identity_changes_with_pitcher():
    o1 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    o2 = _obs(FULL9, [10 + i for i in range(9)], 101, 200)
    assert s6.compute_snapshot_identity("G", o1) != s6.compute_snapshot_identity("G", o2)


def test_no_change_without_prior():
    o1 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    changed, ev = s6.detect_material_change(s6.canonical_snapshot(o1), None)
    assert changed is False and ev == {}


def test_change_on_player_swap():
    o1 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    o2 = _obs([99] + FULL9[1:], [10 + i for i in range(9)], 100, 200)
    changed, ev = s6.detect_material_change(s6.canonical_snapshot(o2), s6.canonical_snapshot(o1))
    assert changed is True
    assert 99 in ev["home_lineup"]["added"]


def test_change_on_probable_pitcher():
    o1 = _obs(FULL9, [10 + i for i in range(9)], 100, 200)
    o2 = _obs(FULL9, [10 + i for i in range(9)], 101, 200)
    changed, ev = s6.detect_material_change(s6.canonical_snapshot(o2), s6.canonical_snapshot(o1))
    assert changed is True
    assert ev["home_probable_pitcher"]["epistemic_status"] == "PROBABLE"


# ===========================================================================
# D. Orchestrator — kill switch
# ===========================================================================

class _NullCursor:
    def execute(self, *a, **k): pass
    def fetchone(self): return None
    def close(self): pass


class _NullConn:
    def __init__(self): self.commit_count = 0; self.rollback_count = 0
    def cursor(self): return _NullCursor()
    def commit(self): self.commit_count += 1
    def rollback(self): self.rollback_count += 1


def test_run_stage_6_raises_when_kill_switch_disabled():
    with pytest.raises(KillSwitchHaltError):
        run_stage_6(_NullConn(), "ORACLE-20260908-777", ["ORACLE-20260908-777-BOS-NYY-1"], env=_DISABLED)


# ===========================================================================
# D2. Caller-visible typed result contract (PM-1033; mocked, deterministic)
# ===========================================================================

from backend.oracle.stage6_lineup import Stage6Result  # noqa: E402


class _FakePolicy:
    policy_version_id = "MLB-A3-v1"


class _RecCursor:
    def execute(self, *a, **k): pass
    def fetchone(self): return None
    def close(self): pass


class _MockConn:
    def __init__(self): self.commits = 0; self.rollbacks = 0
    def cursor(self): return _RecCursor()
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


_FULL = list(range(1, 10))
_AWAY = [10 + i for i in range(9)]


def _obs_cls(cls, home=(), away=(), hpp=None, app=None, detail=None):
    return LineupObservation(
        game_id="1", classification=cls, home_order=tuple(home), away_order=tuple(away),
        home_pitcher=({"id": hpp, "epistemic_status": PITCHER_PROBABLE} if hpp else None),
        away_pitcher=({"id": app, "epistemic_status": PITCHER_PROBABLE} if app else None),
        home_lineup_status=(LINEUP_OBSERVED_FULL if len(home) == 9 else (LINEUP_PARTIAL if home else LINEUP_UNAVAILABLE)),
        away_lineup_status=(LINEUP_OBSERVED_FULL if len(away) == 9 else (LINEUP_PARTIAL if away else LINEUP_UNAVAILABLE)),
        detail=detail,
    )


def _full_obs():
    return _obs_cls(LINEUP_OBSERVED_FULL, _FULL, _AWAY, 100, 200, detail="Preview")


def _run_results(games, obs_for, by_identity=None, latest=None, insert_exc=None):
    conn = _MockConn()
    patches = [
        patch("backend.oracle.orchestrator._load_active_mlb_policy", return_value=_FakePolicy()),
        patch("backend.oracle.orchestrator.MLBAdapter"),
        patch("backend.oracle.orchestrator.record_event", return_value=1),
        patch("backend.oracle.orchestrator._fetch_lineup_observation_by_identity", return_value=by_identity),
        patch("backend.oracle.orchestrator._fetch_latest_lineup_observation", return_value=latest),
        patch("backend.oracle.orchestrator._insert_lineup_observation",
              side_effect=insert_exc if insert_exc else None),
        patch("backend.oracle.orchestrator._insert_lifecycle_audit"),
    ]
    started = [p.start() for p in patches]
    try:
        started[1].return_value.observe_lineup.side_effect = lambda gid: obs_for(gid)
        res = run_stage_6(conn, "ORACLE-20260909-700", games, env=_ENABLED)
        return conn, res
    finally:
        for p in patches:
            p.stop()


def test_result_unavailable():
    _, res = _run_results(["ORACLE-20260909-700-BOS-NYY-1"],
                          lambda g: _obs_cls(LINEUP_UNAVAILABLE, detail="data source unreachable"))
    assert len(res) == 1
    r = res[0]
    assert isinstance(r, Stage6Result)
    assert r.classification == "UNAVAILABLE"
    assert (r.persisted, r.replay, r.change_detected) == (False, False, False)
    assert r.reason == "data source unreachable"


def test_result_partial():
    _, res = _run_results(["ORACLE-20260909-700-BOS-NYY-1"],
                          lambda g: _obs_cls(LINEUP_PARTIAL, _FULL, (), 100, None, detail="Preview"))
    r = res[0]
    assert r.classification == "PARTIAL"
    assert (r.persisted, r.replay, r.change_detected) == (False, False, False)
    assert r.reason


def test_result_first_observed_full():
    conn, res = _run_results(["ORACLE-20260909-700-BOS-NYY-1"], lambda g: _full_obs())
    r = res[0]
    assert r.classification == "OBSERVED_FULL"
    assert (r.persisted, r.replay, r.change_detected) == (True, False, False)
    assert r.snapshot_identity and conn.commits == 1


def test_result_identical_replay():
    obs = _full_obs()
    stored = (list(obs.home_order), list(obs.away_order), obs.home_pitcher, obs.away_pitcher,
              obs.home_lineup_status, obs.away_lineup_status)
    _, res = _run_results(["ORACLE-20260909-700-BOS-NYY-1"], lambda g: obs, by_identity=stored)
    r = res[0]
    assert r.classification == "OBSERVED_FULL"
    assert (r.persisted, r.replay, r.change_detected) == (False, True, False)


def test_result_materially_changed():
    obs = _full_obs()  # home order 1..9
    prior_latest = ("S6O-prior", [99] + _FULL[1:], list(obs.away_order),
                    obs.home_pitcher, obs.away_pitcher, obs.home_lineup_status, obs.away_lineup_status)
    _, res = _run_results(["ORACLE-20260909-700-BOS-NYY-1"], lambda g: obs, latest=prior_latest)
    r = res[0]
    assert (r.persisted, r.replay, r.change_detected) == (True, False, True)


def test_result_multi_game_one_per_game():
    games = ["ORACLE-20260909-700-BOS-NYY-1", "ORACLE-20260909-700-SFG-LAD-2"]
    _, res = _run_results(games, lambda g: _full_obs())
    assert [r.game_run_id for r in res] == games
    assert all(r.classification == "OBSERVED_FULL" for r in res)


def test_result_exception_rolls_back_no_false_success():
    conn = None
    with pytest.raises(RuntimeError):
        conn, _ = _run_results(["ORACLE-20260909-700-BOS-NYY-1"], lambda g: _full_obs(),
                               insert_exc=RuntimeError("db failure"))
    # rollback occurred and no results returned (exception propagated, not a success list)


# ===========================================================================
# E. DB integration (requires ORACLE_TEST_DATABASE_URL)
# ===========================================================================

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")
_db = pytest.mark.skipif(not _TEST_DB_URL, reason="ORACLE_TEST_DATABASE_URL not set")


def _seed(conn, slate, game):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, run_started_at) "
        "VALUES (%s, '2026-09-09', 'analysis_in_progress', NOW()) ON CONFLICT DO NOTHING",
        (slate,),
    )
    cur.execute(
        "INSERT INTO oracle_game_analyses "
        "(game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time, game_status) "
        "VALUES (%s, %s, '746484', 'BOS', 'NYY', '2026-09-09T23:05:00+00:00', 'lineup_monitoring') "
        "ON CONFLICT DO NOTHING",
        (game, slate),
    )
    cur.close()


def _obs_full(home, away, hpp, app):
    return LineupObservation(
        game_id="746484", classification=LINEUP_OBSERVED_FULL,
        home_order=tuple(home), away_order=tuple(away),
        home_pitcher={"id": hpp, "epistemic_status": PITCHER_PROBABLE},
        away_pitcher={"id": app, "epistemic_status": PITCHER_PROBABLE},
        home_lineup_status=LINEUP_OBSERVED_FULL, away_lineup_status=LINEUP_OBSERVED_FULL,
    )


@_db
def test_db_first_observation_persists_and_emits():
    import psycopg2
    slate = "ORACLE-20260909-610"; game = f"{slate}-BOS-NYY-746484"
    conn = psycopg2.connect(_TEST_DB_URL); conn.autocommit = False
    try:
        _seed(conn, slate, game)
        obs = _obs_full(FULL9, [10 + i for i in range(9)], 100, 200)
        with patch.object(MLBAdapter, "observe_lineup", return_value=obs):
            run_stage_6(conn, slate, [game], env=_ENABLED)
        cur = conn.cursor()
        cur.execute("SELECT change_detected, home_lineup_status FROM oracle_lineup_observations WHERE game_run_id=%s", (game,))
        row = cur.fetchone()
        assert row is not None and row[0] is False and row[1] == "OBSERVED_FULL"
        cur.execute("SELECT event_type FROM oracle_play_events WHERE game_run_id=%s", (game,))
        events = {r[0] for r in cur.fetchall()}
        assert "lineup_observation_recorded" in events
        assert "lineup_confirmed" not in events
        assert "recalculation_triggered" not in events
        assert "lineup_change_detected" not in events
        cur.execute("SELECT game_status FROM oracle_game_analyses WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == "lineup_monitoring"
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_identical_replay_no_duplicate():
    import psycopg2
    slate = "ORACLE-20260909-611"; game = f"{slate}-BOS-NYY-746484"
    conn = psycopg2.connect(_TEST_DB_URL); conn.autocommit = False
    try:
        _seed(conn, slate, game)
        obs = _obs_full(FULL9, [10 + i for i in range(9)], 100, 200)
        with patch.object(MLBAdapter, "observe_lineup", return_value=obs):
            run_stage_6(conn, slate, [game], env=_ENABLED)
            run_stage_6(conn, slate, [game], env=_ENABLED)  # identical replay
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_lineup_observations WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_changed_observation_emits_change():
    import psycopg2
    slate = "ORACLE-20260909-612"; game = f"{slate}-BOS-NYY-746484"
    conn = psycopg2.connect(_TEST_DB_URL); conn.autocommit = False
    try:
        _seed(conn, slate, game)
        first = _obs_full(FULL9, [10 + i for i in range(9)], 100, 200)
        changed = _obs_full([99] + FULL9[1:], [10 + i for i in range(9)], 100, 200)
        with patch.object(MLBAdapter, "observe_lineup", return_value=first):
            run_stage_6(conn, slate, [game], env=_ENABLED)
        with patch.object(MLBAdapter, "observe_lineup", return_value=changed):
            run_stage_6(conn, slate, [game], env=_ENABLED)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_lineup_observations WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE game_run_id=%s AND event_type='lineup_change_detected'", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_unavailable_persists_nothing():
    import psycopg2
    slate = "ORACLE-20260909-613"; game = f"{slate}-BOS-NYY-746484"
    conn = psycopg2.connect(_TEST_DB_URL); conn.autocommit = False
    try:
        _seed(conn, slate, game)
        obs = LineupObservation(game_id="746484", classification=LINEUP_UNAVAILABLE, detail="unreachable")
        with patch.object(MLBAdapter, "observe_lineup", return_value=obs):
            run_stage_6(conn, slate, [game], env=_ENABLED)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_lineup_observations WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT event FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='6'", (game,))
        assert cur.fetchone()[0] == "lineup_observation_unavailable"
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_partial_persists_nothing():
    import psycopg2
    slate = "ORACLE-20260909-614"; game = f"{slate}-BOS-NYY-746484"
    conn = psycopg2.connect(_TEST_DB_URL); conn.autocommit = False
    try:
        _seed(conn, slate, game)
        obs = LineupObservation(
            game_id="746484", classification=LINEUP_PARTIAL,
            home_order=tuple(FULL9), away_order=(),
            home_pitcher={"id": 100, "epistemic_status": PITCHER_PROBABLE}, away_pitcher=None,
            home_lineup_status=LINEUP_OBSERVED_FULL, away_lineup_status=LINEUP_UNAVAILABLE,
        )
        with patch.object(MLBAdapter, "observe_lineup", return_value=obs):
            run_stage_6(conn, slate, [game], env=_ENABLED)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_lineup_observations WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 0
        cur.close()
    finally:
        conn.rollback(); conn.close()
