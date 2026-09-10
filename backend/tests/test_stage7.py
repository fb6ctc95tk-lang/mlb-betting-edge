"""Oracle Stage 7 — Final Analysis (Option A) tests (PM-1047 / PM-1049 / PM-1051).

Sections:
  A. Pure helper tests (no DB): bound-input identity, timestamp validity, cutoff
     relationship, differing-input detection.
  B. DB integration (requires ORACLE_TEST_DATABASE_URL): first finalization, exact replay,
     changed provenance (+ dedup), ineligible, unavailable inputs, temporal boundaries,
     cutoff-relationship provenance, immutability, uniqueness reconciliation, rollback/no
     false success, unchanged analytical values, no event emission.

Historical backend baseline is 778 passed / 4 skipped / 0 failed; these tests are additive.
Stage 7 finalization does not establish official lineup confirmation, analytical freshness,
or betting readiness; pitchers remain PROBABLE.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.oracle import stage7_final_analysis as s7
from backend.oracle import orchestrator
from backend.oracle.orchestrator import KillSwitchHaltError, run_stage_7

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "false"}


# ===========================================================================
# A. Pure helper tests (no DB)
# ===========================================================================

def _aware(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_bound_identity_is_deterministic_and_prefixed():
    inputs = s7.bound_inputs("S5R-1", "DV-1", "MLB-A3-v1", _aware(2026, 9, 9, 23, 5), "S6O-x")
    a = s7.compute_bound_input_identity("G", inputs)
    b = s7.compute_bound_input_identity("G", inputs)
    assert a == b
    assert a.startswith("S7F-G-")


def test_bound_identity_covers_all_inputs_not_only_stage5():
    base = dict(stage5_result_id="S5R-1", data_version_id="DV-1",
                policy_version_id="MLB-A3-v1",
                scheduled_cutoff_at=_aware(2026, 9, 9, 23, 5), stage6_snapshot_identity="S6O-x")
    ident = lambda **ov: s7.compute_bound_input_identity("G", s7.bound_inputs(**{**base, **ov}))
    ref = ident()
    assert ident(policy_version_id="MLB-A3-v2") != ref
    assert ident(scheduled_cutoff_at=_aware(2026, 9, 9, 23, 6)) != ref
    assert ident(stage6_snapshot_identity="S6O-y") != ref
    assert ident(data_version_id="DV-2") != ref


def test_is_valid_non_future_observed_at_equal_is_valid():
    t = _aware(2026, 9, 9, 12, 0)
    assert s7.is_valid_non_future_observed_at(t, t) is True


def test_is_valid_non_future_observed_at_future_is_invalid():
    assert s7.is_valid_non_future_observed_at(_aware(2026, 9, 10), _aware(2026, 9, 9)) is False


def test_is_valid_non_future_observed_at_naive_is_invalid():
    naive = datetime(2026, 9, 9, 12, 0)
    assert s7.is_valid_non_future_observed_at(naive, _aware(2026, 9, 9, 13)) is False


def test_cutoff_relationship_before_equal_after():
    cutoff = _aware(2026, 9, 9, 23, 5)
    assert s7.cutoff_relationship(_aware(2026, 9, 9, 22, 0), cutoff) == "before"
    assert s7.cutoff_relationship(cutoff, cutoff) == "equal"
    assert s7.cutoff_relationship(_aware(2026, 9, 9, 23, 30), cutoff) == "after"
    assert s7.cutoff_relationship(datetime(2026, 9, 9), cutoff) is None  # naive → None


def test_differing_bound_inputs_lists_changed_keys():
    a = s7.bound_inputs("S5R-1", "DV-1", "MLB-A3-v1", _aware(2026, 9, 9), "S6O-x")
    b = s7.bound_inputs("S5R-2", "DV-1", "MLB-A3-v1", _aware(2026, 9, 9), "S6O-y")
    assert set(s7.differing_bound_inputs(a, b)) == {"stage5_result_id", "stage6_snapshot_identity"}


def test_kill_switch_first_raises_without_db():
    # No DB touched: kill switch disabled raises before any fetch.
    class _Boom:
        def cursor(self):  # pragma: no cover - must never be reached
            raise AssertionError("DB accessed before kill-switch check")
        def commit(self):  # pragma: no cover
            raise AssertionError
        def rollback(self):  # pragma: no cover
            raise AssertionError
    with pytest.raises(KillSwitchHaltError):
        run_stage_7(_Boom(), "ORACLE-20260909-700", ["ORACLE-20260909-700-BOS-NYY-1"], env=_DISABLED)


# ===========================================================================
# B. DB integration (requires ORACLE_TEST_DATABASE_URL)
# ===========================================================================

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")
_db = pytest.mark.skipif(not _TEST_DB_URL, reason="ORACLE_TEST_DATABASE_URL not set")

_OBS_AT = _aware(2026, 9, 9, 22, 0)          # in the past relative to run time
_CUTOFF_AT = _aware(2026, 9, 9, 23, 5)       # observation is BEFORE cutoff


def _connect():
    import psycopg2
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    return conn


def _seed_game(conn, slate, game, status="lineup_monitoring"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, run_started_at) "
        "VALUES (%s, '2026-09-09', 'analysis_in_progress', NOW()) ON CONFLICT DO NOTHING",
        (slate,),
    )
    cur.execute(
        "INSERT INTO oracle_game_analyses "
        "(game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time, game_status) "
        "VALUES (%s, %s, '746484', 'BOS', 'NYY', '2026-09-09T23:20:00+00:00', %s) ON CONFLICT DO NOTHING",
        (game, slate, status),
    )
    cur.close()


def _seed_stage5(conn, slate, game, s5id, dv="DV-1", verdict="LEAN_HOME"):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_stage5_results
            (stage5_result_id, game_run_id, slate_run_id, ecf_result_id, data_version_id,
             verdict, engine_outputs, model_version, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'stage5-mvp-v1', NOW()) ON CONFLICT DO NOTHING
        """,
        (s5id, game, slate, f"ECF-{game}", dv, verdict, json.dumps({"gse": {"x": 1}})),
    )
    cur.close()


def _seed_cutoff(conn, slate, game, cutoff_at=_CUTOFF_AT, policy="MLB-A3-v1"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_scheduled_cutoffs (game_run_id, slate_run_id, scheduled_cutoff_at, policy_version_id) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (game, slate, cutoff_at, policy),
    )
    cur.close()


def _seed_observation(conn, slate, game, snapshot_identity, observed_at=_OBS_AT):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_lineup_observations
            (game_run_id, slate_run_id, snapshot_identity, observed_at, source,
             home_lineup, away_lineup, home_lineup_status, away_lineup_status,
             home_starting_pitcher, away_starting_pitcher, policy_version_id,
             change_detected, change_evidence)
        VALUES (%s, %s, %s, %s, 'fixture',
                '[1,2,3,4,5,6,7,8,9]'::jsonb, '[10,11,12,13,14,15,16,17,18]'::jsonb,
                'OBSERVED_FULL', 'OBSERVED_FULL',
                %s, %s, 'MLB-A3-v1', false, '{}'::jsonb)
        ON CONFLICT DO NOTHING
        """,
        (game, slate, snapshot_identity, observed_at,
         json.dumps({"id": 100, "epistemic_status": "PROBABLE"}),
         json.dumps({"id": 200, "epistemic_status": "PROBABLE"})),
    )
    cur.close()


def _seed_frozen(conn, slate, game, s5id, snapshot_identity, identity,
                 verdict="LEAN_HOME", dv="DV-1", policy="MLB-A3-v1"):
    """Insert a frozen final record directly (to construct post-finalization states)."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_stage7_final_analysis
            (game_run_id, slate_run_id, stage5_result_id, data_version_id, policy_version_id,
             verdict, scheduled_cutoff_at, stage6_snapshot_identity, stage6_observed_at,
             cutoff_relationship, bound_input_identity, limitations, assessment_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'before',%s,'[]'::jsonb, NOW())
        ON CONFLICT DO NOTHING
        """,
        (game, slate, s5id, dv, policy, verdict, _CUTOFF_AT, snapshot_identity, _OBS_AT, identity),
    )
    cur.close()


def _divergence_audit_count(conn, game):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='7' "
        "AND event='stage7_provenance_divergence'", (game,))
    n = cur.fetchone()[0]
    cur.close()
    return n


def _frozen_row(conn, game):
    cur = conn.cursor()
    cur.execute(
        "SELECT verdict, bound_input_identity, cutoff_relationship, stage6_snapshot_identity, "
        "stage6_observed_at, limitations FROM oracle_stage7_final_analysis WHERE game_run_id=%s",
        (game,),
    )
    row = cur.fetchone()
    cur.close()
    return row


@_db
def test_db_first_finalization_freezes_record_and_transitions():
    slate = "ORACLE-20260909-710"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}", verdict="LEAN_HOME")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert len(results) == 1 and results[0].outcome == "FIRST_FINALIZATION"
        row = _frozen_row(conn, game)
        assert row is not None
        assert row[0] == "LEAN_HOME"                     # verdict copied verbatim
        assert row[2] == "before"                        # cutoff relationship provenance
        assert row[3] == "S6O-first"                     # snapshot provenance bound
        # game transitioned
        cur = conn.cursor()
        cur.execute("SELECT game_status FROM oracle_game_analyses WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == "final_analysis"
        # NO Stage 7 event emitted
        cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 0
        # lifecycle audit recorded
        cur.execute("SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='7' "
                    "AND event='stage7_final_analysis_recorded'", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_exact_replay_no_duplicate_no_write():
    slate = "ORACLE-20260909-711"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)
        results = run_stage_7(conn, slate, [game], env=_ENABLED)  # identical replay
        assert results[0].outcome == "EXACT_REPLAY"
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='7'", (game,))
        assert cur.fetchone()[0] == 1   # only the finalization audit; no divergence row
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_changed_provenance_preserves_frozen_and_dedups():
    slate = "ORACLE-20260909-712"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}", verdict="LEAN_HOME")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)
        frozen_before = _frozen_row(conn, game)
        # A later differing bound input: a new canonical snapshot (deterministic id DESC).
        _seed_observation(conn, slate, game, "S6O-second")
        r1 = run_stage_7(conn, slate, [game], env=_ENABLED)
        r2 = run_stage_7(conn, slate, [game], env=_ENABLED)  # repeat same divergence
        assert r1[0].outcome == "CHANGED_PROVENANCE"
        assert r2[0].outcome == "CHANGED_PROVENANCE"
        assert "stage6_snapshot_identity" in r1[0].differing_inputs
        # Frozen record UNCHANGED (verdict + identity), one row only.
        frozen_after = _frozen_row(conn, game)
        assert frozen_after[0] == frozen_before[0] == "LEAN_HOME"
        assert frozen_after[1] == frozen_before[1]
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        # Divergence audit deduplicated to exactly one for the identical divergence.
        cur.execute("SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='7' "
                    "AND event='stage7_provenance_divergence'", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_unchanged_analytical_values_across_snapshot_change():
    slate = "ORACLE-20260909-713"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}", verdict="STRONG_HOME")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)
        # New observation snapshot (a later observed lineup change).
        _seed_observation(conn, slate, game, "S6O-second")
        run_stage_7(conn, slate, [game], env=_ENABLED)
        row = _frozen_row(conn, game)
        assert row[0] == "STRONG_HOME"           # verdict never adjusted by Stage 6 change
        assert row[3] == "S6O-first"             # frozen provenance not rewritten
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_ineligible_when_not_lineup_monitoring():
    slate = "ORACLE-20260909-714"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game, status="preliminary_analysis")
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert results[0].outcome == "INELIGIBLE"
        assert results[0].reason == "not_in_lineup_monitoring"
        assert _frozen_row(conn, game) is None
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_unavailable_when_missing_stage5():
    slate = "ORACLE-20260909-715"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert results[0].outcome == "UNAVAILABLE_INPUTS"
        assert results[0].reason == "no_stage5_result"
        assert _frozen_row(conn, game) is None
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_unavailable_when_missing_observation():
    slate = "ORACLE-20260909-716"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert results[0].outcome == "UNAVAILABLE_INPUTS"
        assert results[0].reason == "no_canonical_observation"
        assert _frozen_row(conn, game) is None
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_future_observed_at_is_unavailable():
    slate = "ORACLE-20260909-717"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        future = datetime.now(tz=timezone.utc) + timedelta(days=2)
        _seed_observation(conn, slate, game, "S6O-future", observed_at=future)
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert results[0].outcome == "UNAVAILABLE_INPUTS"
        assert results[0].reason == "future_observation_timestamp"
        assert _frozen_row(conn, game) is None
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_frozen_record_is_immutable():
    slate = "ORACLE-20260909-718"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)  # commits the frozen row
        import psycopg2
        cur = conn.cursor()
        with pytest.raises(psycopg2.Error):
            cur.execute("UPDATE oracle_stage7_final_analysis SET verdict='X' WHERE game_run_id=%s", (game,))
        conn.rollback()
        cur = conn.cursor()
        with pytest.raises(psycopg2.Error):
            cur.execute("DELETE FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        conn.rollback()
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_existing_frozen_record_precedence_never_first_finalization():
    """A pre-existing frozen row (as after a concurrent commit) is reconciled by identity,
    never re-finalized: identical inputs → EXACT_REPLAY (uniqueness is not success)."""
    slate = "ORACLE-20260909-719"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)     # first commit
        # Game already advanced; a second invocation must NOT re-finalize.
        results = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert results[0].outcome in ("EXACT_REPLAY", "CHANGED_PROVENANCE")
        assert results[0].outcome != "FIRST_FINALIZATION"
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_rollback_and_raise_on_transaction_failure_no_false_success():
    slate = "ORACLE-20260909-720"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        with patch.object(orchestrator, "_update_game_status", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                run_stage_7(conn, slate, [game], env=_ENABLED)
        # rollback undid everything: no frozen row, status unchanged.
        assert _frozen_row(conn, game) is None
        cur = conn.cursor()
        cur.execute("SELECT game_status FROM oracle_game_analyses WHERE game_run_id=%s", (game,))
        row = cur.fetchone()
        cur.close()
        # The seed itself was rolled back too (never committed), so row is None here.
        assert row is None
    finally:
        conn.rollback(); conn.close()


# --- Correction 2 (PM-1052/PM-1053): missing/unusable current observation after finalization ---

@_db
def test_db_missing_observation_after_finalization_is_unavailable_not_divergence():
    """Frozen record exists but no current canonical observation: must return
    UNAVAILABLE_INPUTS, NOT hash a missing snapshot as None and report CHANGED_PROVENANCE.
    Frozen record preserved; no divergence audit."""
    slate = "ORACLE-20260909-730"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game, status="final_analysis")
        _seed_stage5(conn, slate, game, f"S5R-{game}", verdict="LEAN_HOME")
        _seed_cutoff(conn, slate, game)
        # frozen exists; deliberately NO oracle_lineup_observations row for this game
        _seed_frozen(conn, slate, game, f"S5R-{game}", "S6O-orig", f"S7F-{game}-orig")
        r = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert r[0].outcome == "UNAVAILABLE_INPUTS"
        assert r[0].reason == "no_canonical_observation"
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), MIN(verdict) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        cnt, verdict = cur.fetchone()
        cur.close()
        assert cnt == 1 and verdict == "LEAN_HOME"        # frozen preserved
        assert _divergence_audit_count(conn, game) == 0    # no false divergence
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_frozen_with_unusable_comparison_inputs_is_unavailable():
    """Frozen record exists but Stage 5 result is unreadable: UNAVAILABLE_INPUTS, frozen
    preserved, no divergence audit (contract-defined unusable comparison inputs)."""
    slate = "ORACLE-20260909-731"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game, status="final_analysis")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        _seed_frozen(conn, slate, game, f"S5R-{game}", "S6O-first", f"S7F-{game}-x")  # no stage5 row
        r = run_stage_7(conn, slate, [game], env=_ENABLED)
        assert r[0].outcome == "UNAVAILABLE_INPUTS"
        assert r[0].reason == "unreadable_comparison_inputs"
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
        assert _divergence_audit_count(conn, game) == 0
    finally:
        conn.rollback(); conn.close()


@_db
def test_db_distinct_divergences_remain_distinguishable():
    slate = "ORACLE-20260909-732"; game = f"{slate}-BOS-NYY-746484"
    conn = _connect()
    try:
        _seed_game(conn, slate, game)
        _seed_stage5(conn, slate, game, f"S5R-{game}", verdict="LEAN_HOME")
        _seed_cutoff(conn, slate, game)
        _seed_observation(conn, slate, game, "S6O-first")
        run_stage_7(conn, slate, [game], env=_ENABLED)          # freeze
        _seed_observation(conn, slate, game, "S6O-second")
        run_stage_7(conn, slate, [game], env=_ENABLED)          # divergence #1
        _seed_observation(conn, slate, game, "S6O-third")
        run_stage_7(conn, slate, [game], env=_ENABLED)          # divergence #2 (distinct)
        assert _divergence_audit_count(conn, game) == 2         # two distinct rows
        row = _frozen_row(conn, game)
        assert row[0] == "LEAN_HOME"                            # frozen unchanged
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1
        cur.close()
    finally:
        conn.rollback(); conn.close()


# --- Correction 3 (PM-1052/PM-1053): cross-connection divergence-audit dedup (real concurrency) ---

@_db
def test_db_concurrent_same_divergence_writes_exactly_one_audit():
    """Two INDEPENDENT connections concurrently attempt the same divergence. The
    transaction-scoped advisory lock serializes the check+insert so exactly one matching
    audit row is written; both callers see CHANGED_PROVENANCE; the frozen record is unchanged.
    Coordination uses a Barrier (not sleeps); a lock_timeout bounds any wait so a bug surfaces
    as an error rather than a hang."""
    import threading
    slate = "ORACLE-20260909-733"; game = f"{slate}-BOS-NYY-746484"

    setup = _connect()
    try:
        _seed_game(setup, slate, game)
        _seed_stage5(setup, slate, game, f"S5R-{game}", verdict="LEAN_HOME")
        _seed_cutoff(setup, slate, game)
        _seed_observation(setup, slate, game, "S6O-first")
        run_stage_7(setup, slate, [game], env=_ENABLED)         # FIRST_FINALIZATION (commits)
        _seed_observation(setup, slate, game, "S6O-second")     # introduce divergence
        setup.commit()                                          # visible to both workers
    finally:
        setup.close()

    results = {}
    errors = {}
    barrier = threading.Barrier(2)

    def worker(tag):
        c = _connect()
        try:
            cur = c.cursor(); cur.execute("SET lock_timeout = '20s'"); cur.close()
            barrier.wait()
            results[tag] = run_stage_7(c, slate, [game], env=_ENABLED)
            c.commit()   # release advisory xact lock even on the read-only (skip) path
        except Exception as e:  # noqa: BLE001
            errors[tag] = repr(e)
            try: c.rollback()
            except Exception: pass
        finally:
            c.close()

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert errors == {}, f"worker errors: {errors}"
    assert results["a"][0].outcome == "CHANGED_PROVENANCE"
    assert results["b"][0].outcome == "CHANGED_PROVENANCE"

    v = _connect()
    try:
        assert _divergence_audit_count(v, game) == 1           # exactly one matching audit row
        cur = v.cursor()
        cur.execute("SELECT COUNT(*), MIN(verdict) FROM oracle_stage7_final_analysis WHERE game_run_id=%s", (game,))
        cnt, verdict = cur.fetchone()
        cur.close()
        assert cnt == 1 and verdict == "LEAN_HOME"             # frozen final unchanged
    finally:
        v.close()
