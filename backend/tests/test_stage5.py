"""Oracle Inc-3 — Stage 5 four-engine MVP tests (PM-1009 under PM-1007).

Sections:
  A. GSE engine unit tests
  B. MVE engine unit tests
  C. ODG engine unit tests
  D. SRL engine unit tests
  E. Stage 5 pipeline integration (pure)
  F. Cutoff replay semantics (pure helper via mock connection)
  G. Orchestrator run_stage_5 — kill switch and skip behavior (mocked)
  H. DB integration — policy store, full Stage 5 run, immutability, rollback
     (requires ORACLE_TEST_DATABASE_URL; skipped otherwise)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.oracle.mlb_intelligence import GameEngineInput
from backend.oracle.mlb_intelligence.gse import evaluate_gse
from backend.oracle.mlb_intelligence.mve import evaluate_mve, EDGE_THRESHOLD_PP
from backend.oracle.mlb_intelligence.odg import (
    evaluate_odg,
    VERDICT_ACTIVATE,
    VERDICT_CONDITIONAL,
    VERDICT_NO_PLAY,
)
from backend.oracle.mlb_intelligence.srl import (
    SRLGameInput,
    compute_composite_score,
    rank_slate,
    TIER_TOP,
    TIER_BOTTOM,
)
from backend.oracle.stage5_pipeline import (
    ENGINE_SET,
    Stage5Result,
    run_stage5_pipeline,
)
from backend.oracle import orchestrator
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    Stage5CutoffConflictError,
    _persist_scheduled_cutoff_with_replay,
    run_stage_5,
)

_NOW = datetime(2026, 9, 8, 18, 0, 0, tzinfo=timezone.utc)
_ENABLED_ENV = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED_ENV = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "false"}


# ===========================================================================
# A. GSE
# ===========================================================================

def test_gse_matchup_established_high_confidence():
    r = evaluate_gse(0.8, {"data_completeness": 0.9, "data_freshness": 0.9},
                     {"home_pitcher": "Ace A", "away_pitcher": "Ace B"})
    assert r.engine == "GSE"
    assert r.pitching_matchup_established is True
    assert r.script_confidence == round(0.6 * 0.8 + 0.4, 4)
    assert r.script_profile == "PITCHING_ESTABLISHED"


def test_gse_no_matchup_is_uncertain():
    r = evaluate_gse(0.8, {}, {"home_pitcher": "", "away_pitcher": ""})
    assert r.pitching_matchup_established is False
    assert r.script_profile == "UNCERTAIN_MATCHUP"
    assert r.script_confidence == round(0.6 * 0.8, 4)


def test_gse_is_deterministic():
    payload = {"home_pitcher": "A", "away_pitcher": "B"}
    a = evaluate_gse(0.5, {}, payload)
    b = evaluate_gse(0.5, {}, payload)
    assert a == b


def test_gse_reports_unwired_data_limitations():
    r = evaluate_gse(0.5, {}, {"home_pitcher": "A", "away_pitcher": "B"})
    assert "weather_not_integrated" in r.confidence_limitations
    assert "confirmed_lineup_not_integrated" in r.confidence_limitations


# ===========================================================================
# B. MVE
# ===========================================================================

def test_mve_no_market_is_insufficient():
    r = evaluate_mve(0.9, 0.9, market_moneyline=None)
    assert r.edge_assessment == "INSUFFICIENT_MARKET_DATA"
    assert r.market_price_available is False
    assert r.market_implied_probability is None
    assert "no_live_odds_provider_wired" in r.confidence_limitations


def test_mve_positive_edge_when_market_underprices():
    # fair ~0.65 (ecf=1, conf=1); market +100 -> implied 0.5 -> edge ~15pp.
    r = evaluate_mve(1.0, 1.0, market_moneyline={"home": 100})
    assert r.market_price_available is True
    assert r.market_implied_probability == 0.5
    assert r.edge_percentage_points >= EDGE_THRESHOLD_PP
    assert r.edge_assessment == "EDGE"


def test_mve_no_edge_when_fairly_priced():
    # fair 0.5 (ecf=0.5, conf=0.5); market +100 -> implied 0.5 -> edge 0.
    r = evaluate_mve(0.5, 0.5, market_moneyline={"home": 100})
    assert r.edge_percentage_points == 0.0
    assert r.edge_assessment == "NO_EDGE"


def test_mve_implied_probability_favorite_math():
    r = evaluate_mve(0.5, 0.5, market_moneyline={"home": -200})
    assert r.market_implied_probability == round(200 / 300, 4)


def test_mve_fair_probability_bounded_near_half():
    r = evaluate_mve(1.0, 1.0, market_moneyline=None)
    assert 0.35 <= r.model_fair_probability <= 0.65


# ===========================================================================
# C. ODG
# ===========================================================================

def test_odg_insufficient_market_is_no_play():
    r = evaluate_odg(1.0, 0.9, "INSUFFICIENT_MARKET_DATA", None)
    assert r.verdict == VERDICT_NO_PLAY
    assert "insufficient_market_data" in r.reasons


def test_odg_low_confidence_is_no_play():
    r = evaluate_odg(1.0, 0.3, "EDGE", 10.0)
    assert r.verdict == VERDICT_NO_PLAY
    assert "low_script_confidence" in r.reasons


def test_odg_no_edge_is_no_play():
    r = evaluate_odg(1.0, 0.8, "NO_EDGE", 1.0)
    assert r.verdict == VERDICT_NO_PLAY
    assert "no_market_edge" in r.reasons


def test_odg_edge_high_confidence_is_activate():
    r = evaluate_odg(1.0, 0.7, "EDGE", 8.0)
    assert r.verdict == VERDICT_ACTIVATE
    assert "positive_market_edge" in r.reasons


def test_odg_edge_moderate_confidence_is_conditional():
    r = evaluate_odg(1.0, 0.5, "EDGE", 5.0)
    assert r.verdict == VERDICT_CONDITIONAL


def test_odg_issues_exactly_one_verdict_value():
    r = evaluate_odg(1.0, 0.7, "EDGE", 8.0)
    assert r.verdict in {VERDICT_ACTIVATE, VERDICT_CONDITIONAL, VERDICT_NO_PLAY}


def test_odg_propagates_confidence_limitations():
    r = evaluate_odg(1.0, 0.9, "INSUFFICIENT_MARKET_DATA", None,
                     inherited_limitations=("weather_not_integrated",))
    assert "weather_not_integrated" in r.confidence_limitations


# ===========================================================================
# D. SRL
# ===========================================================================

def test_srl_ranks_by_composite_descending():
    entries = [
        SRLGameInput("g-low", 0.2, 0.1, None),
        SRLGameInput("g-high", 0.9, 0.9, 10.0),
    ]
    result = rank_slate(entries)
    assert result["g-high"].rank == 1
    assert result["g-low"].rank == 2
    assert result["g-high"].tier == TIER_TOP
    assert result["g-low"].tier == TIER_BOTTOM


def test_srl_tie_broken_deterministically_by_game_run_id():
    entries = [
        SRLGameInput("g-b", 0.5, 0.5, None),
        SRLGameInput("g-a", 0.5, 0.5, None),
    ]
    result = rank_slate(entries)
    assert result["g-a"].rank == 1  # ascending id breaks the tie
    assert result["g-b"].rank == 2


def test_srl_single_game_is_top():
    result = rank_slate([SRLGameInput("solo", 0.4, 0.4, None)])
    assert result["solo"].rank == 1
    assert result["solo"].tier == TIER_TOP


def test_srl_composite_score_bounds():
    assert compute_composite_score(1.0, 1.0, 100.0) <= 1.0
    assert compute_composite_score(0.0, 0.0, None) == 0.0


# ===========================================================================
# E. Pipeline integration (pure)
# ===========================================================================

def _make_input(game_run_id, ecf_score=0.8, payload=None, market=None):
    return GameEngineInput(
        game_run_id=game_run_id,
        ecf_result_id=f"ECFR-{game_run_id}",
        data_version_id=f"DV-{game_run_id}",
        ecf_score=ecf_score,
        ecf_components={"data_completeness": 0.9, "data_freshness": 0.9},
        ecf_model_version="structural-ecf-v1",
        preliminary_payload=payload or {"home_pitcher": "A", "away_pitcher": "B"},
        first_pitch_time=_NOW + timedelta(hours=3),
        market_moneyline=market,
    )


def test_pipeline_produces_result_per_game():
    inputs = [_make_input("g1"), _make_input("g2")]
    results = run_stage5_pipeline("ORACLE-20260908-777", inputs, _NOW)
    assert set(results.keys()) == {"g1", "g2"}
    for r in results.values():
        assert isinstance(r, Stage5Result)
        assert set(r.engine_outputs.keys()) == {"gse", "mve", "odg", "srl"}
        assert r.verdict in {VERDICT_ACTIVATE, VERDICT_CONDITIONAL, VERDICT_NO_PLAY}


def test_pipeline_never_emits_phie_or_ce():
    results = run_stage5_pipeline("ORACLE-20260908-777", [_make_input("g1")], _NOW)
    outputs = results["g1"].engine_outputs
    assert "phie" not in outputs
    assert "ce" not in outputs
    engines = {v["engine"] for v in outputs.values()}
    assert engines == set(ENGINE_SET)


def test_pipeline_binds_ecf_identity():
    results = run_stage5_pipeline("ORACLE-20260908-777", [_make_input("g1")], _NOW)
    assert results["g1"].ecf_result_id == "ECFR-g1"
    assert results["g1"].data_version_id == "DV-g1"


def test_pipeline_is_deterministic():
    inputs = [_make_input("g1"), _make_input("g2")]
    a = run_stage5_pipeline("S", inputs, _NOW)
    b = run_stage5_pipeline("S", inputs, _NOW)
    assert a == b


def test_pipeline_no_market_yields_no_play():
    results = run_stage5_pipeline("S", [_make_input("g1", market=None)], _NOW)
    assert results["g1"].verdict == VERDICT_NO_PLAY


# ===========================================================================
# F. Cutoff replay semantics (mock connection)
# ===========================================================================

class _ReplayCursor:
    def __init__(self, store):
        self._store = store
        self._result = None

    def execute(self, sql, params=None):
        s = sql.strip().upper()
        if s.startswith("SELECT"):
            self._result = self._store.get(params[0])
        elif s.startswith("INSERT"):
            game_run_id, slate, cutoff, policy = params
            self._store[game_run_id] = (slate, cutoff, policy)

    def fetchone(self):
        return self._result

    def close(self):
        pass


class _ReplayConn:
    def __init__(self):
        self.store = {}

    def cursor(self):
        return _ReplayCursor(self.store)


def test_cutoff_first_insert_persists():
    conn = _ReplayConn()
    cutoff = _NOW + timedelta(hours=3)
    _persist_scheduled_cutoff_with_replay(conn, "g1", "S", cutoff, "MLB-A3-v1")
    assert conn.store["g1"] == ("S", cutoff, "MLB-A3-v1")


def test_cutoff_equal_replay_is_idempotent():
    conn = _ReplayConn()
    cutoff = _NOW + timedelta(hours=3)
    _persist_scheduled_cutoff_with_replay(conn, "g1", "S", cutoff, "MLB-A3-v1")
    # Same immutable values on replay — no error, no duplicate.
    _persist_scheduled_cutoff_with_replay(conn, "g1", "S", cutoff, "MLB-A3-v1")
    assert conn.store["g1"] == ("S", cutoff, "MLB-A3-v1")


def test_cutoff_conflicting_replay_raises():
    conn = _ReplayConn()
    cutoff = _NOW + timedelta(hours=3)
    _persist_scheduled_cutoff_with_replay(conn, "g1", "S", cutoff, "MLB-A3-v1")
    with pytest.raises(Stage5CutoffConflictError):
        _persist_scheduled_cutoff_with_replay(
            conn, "g1", "S", cutoff + timedelta(minutes=1), "MLB-A3-v1"
        )


# ===========================================================================
# G. Orchestrator run_stage_5 — kill switch and skip (mocked connection)
# ===========================================================================

class _NullCursor:
    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return None

    def close(self):
        pass


class _NullConn:
    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _NullCursor()

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def test_run_stage_5_raises_when_kill_switch_disabled():
    with pytest.raises(KillSwitchHaltError):
        run_stage_5(_NullConn(), "ORACLE-20260908-777", ["g1"], env=_DISABLED_ENV)


def test_run_stage_5_skips_when_no_ecf_results(monkeypatch):
    # Policy present, but no ECF rows -> nothing to process, commit empty.
    class _Policy:
        policy_version_id = "MLB-A3-v1"
        time_cutoff_offset = timedelta(minutes=-15)
    monkeypatch.setattr(orchestrator, "_load_active_mlb_policy", lambda conn: _Policy())
    conn = _NullConn()
    run_stage_5(conn, "ORACLE-20260908-777", ["g1", "g2"], env=_ENABLED_ENV)
    assert conn.commit_count == 1
    assert conn.rollback_count == 0


# ===========================================================================
# H. DB integration (requires ORACLE_TEST_DATABASE_URL)
# ===========================================================================

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")

_db = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="ORACLE_TEST_DATABASE_URL not set — Stage 5 DB integration skipped",
)


@_db
def test_policy_store_returns_active_mlb_policy():
    import psycopg2
    from backend.oracle.sport_policy_store import PolicyReadOutcome
    from backend.oracle.sport_policy_store_db import MLBSportPolicyStore

    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    try:
        resp = MLBSportPolicyStore(conn).get_active_policy("MLB")
        assert resp.outcome is PolicyReadOutcome.RECORD_RETURNED
        assert resp.record.policy_version_id == "MLB-A3-v1"
        assert resp.record.time_cutoff_offset == timedelta(seconds=-900)
        assert "play_locked" in resp.record.finalization_event_type_list
    finally:
        conn.rollback()
        conn.close()


def _seed_game_with_ecf(conn, slate_run_id, game_run_id, first_pitch, ecf_score=0.9):
    """Insert slate, game, preliminary data, and an ECF result for one game."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, run_started_at) "
        "VALUES (%s, %s, 'analysis_in_progress', NOW()) ON CONFLICT DO NOTHING",
        (slate_run_id, first_pitch.date()),
    )
    cur.execute(
        "INSERT INTO oracle_game_analyses "
        "(game_run_id, slate_run_id, external_game_id, home_team, away_team, "
        " first_pitch_time, game_status) "
        "VALUES (%s, %s, '746484', 'BOS', 'NYY', %s, 'preliminary_analysis')",
        (game_run_id, slate_run_id, first_pitch),
    )
    cur.execute(
        "INSERT INTO oracle_preliminary_data "
        "(game_run_id, slate_run_id, data_version_id, game_id, gathered_at, raw_payload) "
        "VALUES (%s, %s, %s, '746484', NOW(), %s)",
        (game_run_id, slate_run_id, f"DV-{game_run_id}",
         json.dumps({"home_pitcher": "Ace A", "away_pitcher": "Ace B"})),
    )
    cur.execute(
        "INSERT INTO oracle_ecf_results "
        "(ecf_result_id, game_run_id, data_version_id, ecf_score, component_scores, "
        " model_version, computed_at) "
        "VALUES (%s, %s, %s, %s, %s, 'structural-ecf-v1', NOW())",
        (f"ECFR-{game_run_id}", game_run_id, f"DV-{game_run_id}", ecf_score,
         json.dumps({"data_completeness": 0.9, "data_freshness": 0.9, "data_payload_density": 0.8})),
    )
    cur.close()


@_db
def test_run_stage_5_full_persists_result_output_cutoff_and_event():
    import psycopg2
    slate = "ORACLE-20260908-701"
    game = f"{slate}-BOS-NYY"
    first_pitch = datetime(2026, 9, 9, 23, 5, 0, tzinfo=timezone.utc)

    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    try:
        _seed_game_with_ecf(conn, slate, game, first_pitch)
        run_stage_5(conn, slate, [game], env=_ENABLED_ENV)

        cur = conn.cursor()
        cur.execute("SELECT verdict FROM oracle_stage5_results WHERE game_run_id = %s", (game,))
        assert cur.fetchone() is not None

        cur.execute(
            "SELECT consumer_status FROM oracle_preliminary_outputs WHERE game_run_id = %s",
            (game,),
        )
        assert cur.fetchone()[0] == "Preliminary"

        cur.execute(
            "SELECT scheduled_cutoff_at, policy_version_id FROM oracle_scheduled_cutoffs "
            "WHERE game_run_id = %s",
            (game,),
        )
        cutoff_at, policy_version = cur.fetchone()
        assert policy_version == "MLB-A3-v1"
        assert cutoff_at == first_pitch - timedelta(minutes=15)

        cur.execute(
            "SELECT game_status FROM oracle_game_analyses WHERE game_run_id = %s", (game,)
        )
        assert cur.fetchone()[0] == "lineup_monitoring"

        cur.execute(
            "SELECT event_type FROM oracle_play_events WHERE game_run_id = %s", (game,)
        )
        events = {row[0] for row in cur.fetchall()}
        assert "multi_model_analysis_completed" in events
        assert "phie_completed" not in events
        assert "ce_completed" not in events

        cur.execute(
            "SELECT event FROM oracle_lifecycle_audit WHERE game_run_id = %s AND stage = '5'",
            (game,),
        )
        assert cur.fetchone()[0] == "multi_model_analysis_completed"
        cur.close()
    finally:
        conn.rollback()
        conn.close()


@_db
def test_run_stage_5_preliminary_output_is_immutable():
    import psycopg2
    import psycopg2.errors
    slate = "ORACLE-20260908-702"
    game = f"{slate}-BOS-NYY"
    first_pitch = datetime(2026, 9, 9, 23, 5, 0, tzinfo=timezone.utc)

    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    try:
        _seed_game_with_ecf(conn, slate, game, first_pitch)
        run_stage_5(conn, slate, [game], env=_ENABLED_ENV)
        cur = conn.cursor()
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(
                "UPDATE oracle_preliminary_outputs SET verdict = 'X' WHERE game_run_id = %s",
                (game,),
            )
        cur.close()
        conn.rollback()
    finally:
        conn.rollback()
        conn.close()


@_db
def test_run_stage_5_cutoff_conflict_rolls_back_with_no_partial_result():
    import psycopg2
    slate = "ORACLE-20260908-703"
    game = f"{slate}-BOS-NYY"
    first_pitch = datetime(2026, 9, 9, 23, 5, 0, tzinfo=timezone.utc)

    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    try:
        _seed_game_with_ecf(conn, slate, game, first_pitch)
        # Pre-existing cutoff with a CONFLICTING timestamp for the same game.
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO oracle_scheduled_cutoffs "
            "(game_run_id, slate_run_id, scheduled_cutoff_at, policy_version_id) "
            "VALUES (%s, %s, %s, 'MLB-A3-v1')",
            (game, slate, first_pitch),  # wrong: not first_pitch - 15m
        )
        cur.close()
        conn.commit()

        with pytest.raises(Stage5CutoffConflictError):
            run_stage_5(conn, slate, [game], env=_ENABLED_ENV)

        # After rollback, no Stage 5 result may have been committed for this game.
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage5_results WHERE game_run_id = %s", (game,))
        assert cur.fetchone()[0] == 0
        cur.close()
    finally:
        conn.rollback()
        conn.close()
