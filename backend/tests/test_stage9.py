"""Oracle Stage 9 — Pregame Lock (FULL immutable lock) tests (PM-1089 / PM-1091 / PM-1092 / PM-1093).

Sections:
  A. Pure helper tests (no DB): lock identity, timestamp validity, strict before-cutoff freeze
     boundary, cutoff relationship, reason codes, honest limitations.
  B. DB integration (requires ORACLE_TEST_DATABASE_URL): first lock, ineligible variants
     (not-in-slate, no-admission, not-activation-eligible, slate-already-locked later arrival,
     at/after-cutoff), unavailable/missing evidence, historical replay, changed provenance
     (+ dedup), aggregate completion vs incomplete slate, empty slate, immutability, one-only
     play_locked event, rollback / no false success.
  C. Real independent-transaction slate-lock contention: different games complete the slate;
     same-game predecessor commit → historical replay; predecessor rollback → fresh lock;
     post-wait cutoff decisions (equal/after reject, before locks); concurrent divergence dedup.
  D. Defensive uniqueness recovery (SEPARATE from normal contention): unexpected 23505 with a
     verified committed lock → historical reconciliation; with none → rollback-and-raise.

Stage 9 pregame lock is a finalization only: no bet, edge, official confirmation, source
freshness, or betting readiness; it binds only the frozen Stage-8 admission and Stage-7 evidence
and revalidates no live input. It does NOT re-run Stage-8 admission eligibility. A historical lock
(EXACT_REPLAY) is not perpetual permission after cutoff.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.oracle import stage9_pregame_lock as s9
from backend.oracle import orchestrator
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    Stage9LockError,
    run_stage_9,
)

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "false"}


def _aware(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ===========================================================================
# A. Pure helper tests (no DB)
# ===========================================================================

def test_lock_identity_is_deterministic_and_prefixed():
    a = s9.compute_lock_identity("G", "S8A-G-abc", "S7F-G-xyz")
    b = s9.compute_lock_identity("G", "S8A-G-abc", "S7F-G-xyz")
    assert a == b
    assert a.startswith("S9L-G-")


def test_lock_identity_changes_with_any_bound_provenance():
    ref = s9.compute_lock_identity("G", "S8A-aaa", "S7F-aaa")
    assert s9.compute_lock_identity("G", "S8A-bbb", "S7F-aaa") != ref   # different admission identity
    assert s9.compute_lock_identity("G", "S8A-aaa", "S7F-bbb") != ref   # different frozen Stage-7
    assert s9.compute_lock_identity("H", "S8A-aaa", "S7F-aaa") != ref   # different game


def test_is_timezone_aware():
    assert s9.is_timezone_aware(_aware(2026, 9, 11, 12))
    assert not s9.is_timezone_aware(datetime(2026, 9, 11, 12))       # naive
    assert not s9.is_timezone_aware("2026-09-11T12:00:00Z")          # not a datetime
    assert not s9.is_timezone_aware(None)


def test_is_before_cutoff_is_strict():
    decision = _aware(2026, 9, 11, 12, 0)
    assert s9.is_before_cutoff(decision, _aware(2026, 9, 11, 12, 1))       # before → True
    assert not s9.is_before_cutoff(decision, _aware(2026, 9, 11, 12, 0))   # equal → False (rejects)
    assert not s9.is_before_cutoff(decision, _aware(2026, 9, 11, 11, 59))  # after → False


def test_is_before_cutoff_false_for_naive_or_missing():
    decision = _aware(2026, 9, 11, 12, 0)
    assert not s9.is_before_cutoff(decision, datetime(2026, 9, 11, 13))    # naive cutoff
    assert not s9.is_before_cutoff(datetime(2026, 9, 11, 12), _aware(2026, 9, 11, 13))  # naive decision
    assert not s9.is_before_cutoff(decision, None)


def test_cutoff_relationship_classification():
    decision = _aware(2026, 9, 11, 12, 0)
    assert s9.cutoff_relationship(decision, _aware(2026, 9, 11, 12, 5)) == s9.CUTOFF_BEFORE
    assert s9.cutoff_relationship(decision, _aware(2026, 9, 11, 12, 0)) == s9.CUTOFF_EQUAL
    assert s9.cutoff_relationship(decision, _aware(2026, 9, 11, 11, 0)) == s9.CUTOFF_AFTER
    assert s9.cutoff_relationship(decision, None) is None


def test_reason_codes_are_bounded():
    assert s9.REASON_NOT_IN_SLATE == "not_in_slate"
    assert s9.REASON_SLATE_ALREADY_LOCKED == "slate_already_locked"
    assert s9.REASON_NO_ADMISSION == "no_admission"
    assert s9.REASON_NOT_ACTIVATION_ELIGIBLE == "not_activation_eligible"
    assert s9.REASON_AT_OR_AFTER_CUTOFF == "at_or_after_cutoff"


def test_standing_limitations_are_honest_and_non_empty():
    lims = s9.standing_limitations()
    assert "pregame_lock_only_not_a_play" in lims
    assert "not_source_freshness_or_betting_readiness" in lims
    assert "historical_lock_not_perpetual_permission_after_cutoff" in lims


# ===========================================================================
# B. DB integration (requires ORACLE_TEST_DATABASE_URL)
# ===========================================================================

_TEST_DB_URL = os.getenv("ORACLE_TEST_DATABASE_URL")
_db = pytest.mark.skipif(not _TEST_DB_URL, reason="ORACLE_TEST_DATABASE_URL not set")


def _future_cutoff():
    return datetime.now(tz=timezone.utc) + timedelta(days=1)


def _past_cutoff():
    return datetime.now(tz=timezone.utc) - timedelta(days=1)


def _connect():
    import psycopg2
    conn = psycopg2.connect(_TEST_DB_URL)
    conn.autocommit = False
    return conn


def _seed_slate(conn, slate, run_status="activation_window_open"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, run_started_at) "
        "VALUES (%s, '2026-09-09', %s, NOW()) ON CONFLICT DO NOTHING",
        (slate, run_status),
    )
    cur.close()


def _seed_game(conn, slate, game, status="activation_eligible"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_game_analyses "
        "(game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time, game_status) "
        "VALUES (%s, %s, '746484', 'BOS', 'NYY', '2026-09-09T23:20:00+00:00', %s) ON CONFLICT DO NOTHING",
        (game, slate, status),
    )
    cur.close()


def _seed_admission(conn, slate, game, activation_identity, stage7_identity, cutoff_at):
    """Insert a committed Stage-8 admission row directly (Stage 9's frozen input)."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_stage8_activation_window
            (game_run_id, slate_run_id, stage7_bound_input_identity, activation_identity,
             scheduled_cutoff_at, cutoff_relationship, limitations, assessment_at)
        VALUES (%s,%s,%s,%s,%s,'before','[]'::jsonb, NOW())
        ON CONFLICT DO NOTHING
        """,
        (game, slate, stage7_identity, activation_identity, cutoff_at),
    )
    cur.close()


def _seed_lock(conn, slate, game, activation_identity, stage7_identity, cutoff_at, lock_identity=None):
    """Insert a committed Stage-9 lock row directly (to construct post-lock states)."""
    cur = conn.cursor()
    lid = lock_identity or s9.compute_lock_identity(game, activation_identity, stage7_identity)
    cur.execute(
        """
        INSERT INTO oracle_stage9_pregame_lock
            (game_run_id, slate_run_id, activation_identity, stage7_bound_input_identity,
             lock_identity, scheduled_cutoff_at, cutoff_relationship, limitations, decision_at)
        VALUES (%s,%s,%s,%s,%s,%s,'before','[]'::jsonb, NOW())
        ON CONFLICT DO NOTHING
        """,
        (game, slate, activation_identity, stage7_identity, lid, cutoff_at),
    )
    cur.close()


def _lock_row(conn, game):
    cur = conn.cursor()
    cur.execute(
        "SELECT lock_identity, activation_identity, stage7_bound_input_identity, cutoff_relationship "
        "FROM oracle_stage9_pregame_lock WHERE game_run_id=%s",
        (game,),
    )
    row = cur.fetchone()
    cur.close()
    return row


def _game_status(conn, game):
    cur = conn.cursor()
    cur.execute("SELECT game_status FROM oracle_game_analyses WHERE game_run_id=%s", (game,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def _slate_status(conn, slate):
    cur = conn.cursor()
    cur.execute("SELECT run_status FROM oracle_slate_runs WHERE slate_run_id=%s", (slate,))
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def _divergence_audit_count(conn, game):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='9' "
        "AND event='stage9_pregame_lock_divergence'", (game,))
    n = cur.fetchone()[0]
    cur.close()
    return n


def _play_locked_count(conn, slate):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id=%s AND event_type='play_locked'",
        (slate,))
    n = cur.fetchone()[0]
    cur.close()
    return n


@_db
def test_first_lock_locks_game_and_completes_slate():
    slate = "ORACLE-20260909-901"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert len(res) == 1 and res[0].outcome == s9.LOCKED
        assert res[0].cutoff_relationship == "before"
        assert res[0].lock_identity.startswith("S9L-")
        assert _game_status(c, game) == "pregame_locked"
        assert _slate_status(c, slate) == "pregame_locked"     # sole admission locked → aggregate complete
        assert _lock_row(c, game) is not None
        assert _play_locked_count(c, slate) == 1               # exactly one finalization event
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_not_activation_eligible():
    slate = "ORACLE-20260909-902"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game, status="final_analysis")
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "not_activation_eligible"
        assert _lock_row(c, game) is None
        assert _slate_status(c, slate) == "activation_window_open"
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_no_admission():
    slate = "ORACLE-20260909-903"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)   # eligible but NO Stage-8 admission
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "no_admission"
        assert _lock_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_membership_foreign_slate_rejected_without_writes():
    s_true = "ORACLE-20260909-904"; s_other = "ORACLE-20260909-905"
    game = f"{s_true}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, s_true); _seed_slate(c, s_other)
        _seed_game(c, s_true, game)
        _seed_admission(c, s_true, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_9(c, s_other, [game], env=_ENABLED)   # foreign locked slate
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "not_in_slate"
        assert _lock_row(c, game) is None
        assert _game_status(c, game) == "activation_eligible"
        assert _slate_status(c, s_other) == "activation_window_open"
    finally:
        c.rollback(); c.close()


@_db
def test_membership_missing_game_row_rejected():
    slate = "ORACLE-20260909-906"; game = f"{slate}-DOES-NOT-EXIST"
    c = _connect()
    try:
        _seed_slate(c, slate); c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "not_in_slate"
        assert _lock_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_later_arrival_rejected_after_slate_locked():
    """A game presented after the slate is pregame_locked is rejected (slate_already_locked)."""
    slate = "ORACLE-20260909-907"; game = f"{slate}-LATE-1"
    c = _connect()
    try:
        _seed_slate(c, slate, run_status="pregame_locked")   # slate already locked
        _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "slate_already_locked"
        assert _lock_row(c, game) is None
        assert _slate_status(c, slate) == "pregame_locked"
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_after_cutoff():
    slate = "ORACLE-20260909-908"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _past_cutoff())   # frozen cutoff passed
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.INELIGIBLE and res[0].reason == "at_or_after_cutoff"
        assert _lock_row(c, game) is None
        assert _slate_status(c, slate) == "activation_window_open"   # incomplete; no closure invented
    finally:
        c.rollback(); c.close()


@_db
def test_empty_slate_locks_nothing():
    slate = "ORACLE-20260909-909"
    c = _connect()
    try:
        _seed_slate(c, slate); c.commit()
        res = run_stage_9(c, slate, [], env=_ENABLED)
        assert res == []
        assert _slate_status(c, slate) == "activation_window_open"
    finally:
        c.rollback(); c.close()


@_db
def test_mixed_slate_locks_eligible_only_and_stays_incomplete():
    """One admitted+eligible game locks; a second admission that is not eligible cannot lock, so the
    slate is NOT complete and stays open (no invented closure)."""
    slate = "ORACLE-20260909-910"
    g_ok = f"{slate}-OK-1"; g_bad = f"{slate}-BAD-2"
    c = _connect()
    try:
        _seed_slate(c, slate)
        _seed_game(c, slate, g_ok); _seed_admission(c, slate, g_ok, "S8A-ok", "S7F-ok", _future_cutoff())
        _seed_game(c, slate, g_bad, status="final_analysis")
        _seed_admission(c, slate, g_bad, "S8A-bad", "S7F-bad", _future_cutoff())
        c.commit()
        res = {r.game_run_id: r for r in run_stage_9(c, slate, [g_ok, g_bad], env=_ENABLED)}
        assert res[g_ok].outcome == s9.LOCKED
        assert res[g_bad].outcome == s9.INELIGIBLE and res[g_bad].reason == "not_activation_eligible"
        assert _lock_row(c, g_ok) is not None and _lock_row(c, g_bad) is None
        assert _slate_status(c, slate) == "activation_window_open"   # incomplete → not transitioned
    finally:
        c.rollback(); c.close()


@_db
def test_all_admissions_locked_completes_slate():
    slate = "ORACLE-20260909-911"
    g1 = f"{slate}-G1"; g2 = f"{slate}-G2"
    c = _connect()
    try:
        _seed_slate(c, slate)
        _seed_game(c, slate, g1); _seed_admission(c, slate, g1, "S8A-1", "S7F-1", _future_cutoff())
        _seed_game(c, slate, g2); _seed_admission(c, slate, g2, "S8A-2", "S7F-2", _future_cutoff())
        c.commit()
        res = {r.game_run_id: r for r in run_stage_9(c, slate, [g1, g2], env=_ENABLED)}
        assert res[g1].outcome == s9.LOCKED and res[g2].outcome == s9.LOCKED
        assert _slate_status(c, slate) == "pregame_locked"          # both admissions locked → complete
        assert _play_locked_count(c, slate) == 2
    finally:
        c.rollback(); c.close()


@_db
def test_exact_replay_is_read_only():
    slate = "ORACLE-20260909-912"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        run_stage_9(c, slate, [game], env=_ENABLED)          # LOCKED
        before_events = _play_locked_count(c, slate)
        res = run_stage_9(c, slate, [game], env=_ENABLED)    # re-invoke
        assert res[0].outcome == s9.EXACT_REPLAY
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage9_pregame_lock WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1                        # no second lock row
        cur.close()
        assert _play_locked_count(c, slate) == before_events  # no second event
        assert _divergence_audit_count(c, game) == 0
    finally:
        c.rollback(); c.close()


@_db
def test_changed_provenance_writes_one_dedup_audit_and_preserves_row():
    slate = "ORACLE-20260909-913"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game, status="pregame_locked")
        # current admission provenance = S8A-current; existing lock bound to an OLD provenance
        _seed_admission(c, slate, game, "S8A-current", "S7F-current", _future_cutoff())
        _seed_lock(c, slate, game, "S8A-OLD", "S7F-OLD", _future_cutoff())
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.CHANGED_PROVENANCE
        assert set(res[0].differing_inputs) == {"activation_identity", "stage7_bound_input_identity"}
        assert _divergence_audit_count(c, game) == 1
        run_stage_9(c, slate, [game], env=_ENABLED)          # dedup → still one
        assert _divergence_audit_count(c, game) == 1
        assert _lock_row(c, game)[1] == "S8A-OLD"            # lock row unchanged
        assert _play_locked_count(c, slate) == 0             # divergence emits no finalization event
    finally:
        c.rollback(); c.close()


@_db
def test_unavailable_inputs_when_admission_missing_after_lock():
    slate = "ORACLE-20260909-914"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game, status="pregame_locked")
        _seed_lock(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())   # lock but NO admission
        c.commit()
        res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.UNAVAILABLE_INPUTS
        assert res[0].reason == "unreadable_comparison_inputs"
        assert _lock_row(c, game) is not None                 # preserved
        assert _divergence_audit_count(c, game) == 0
    finally:
        c.rollback(); c.close()


@_db
def test_cutoff_missing_or_invalid_yields_unavailable_inputs():
    """A non-tz-aware frozen cutoff in the admission maps to UNAVAILABLE_INPUTS (no lock)."""
    slate = "ORACLE-20260909-915"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        naive_admission = ("S8A-1", "S7F-a", datetime(2026, 12, 1, 0, 0), "before")  # naive cutoff idx 2
        with patch.object(orchestrator, "_fetch_stage8_activation", return_value=naive_admission):
            res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.UNAVAILABLE_INPUTS
        assert res[0].reason == "cutoff_missing_or_invalid"
        assert _lock_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_lock_row_is_immutable():
    slate = "ORACLE-20260909-916"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        run_stage_9(c, slate, [game], env=_ENABLED)
        import psycopg2
        with pytest.raises(psycopg2.Error):
            cur = c.cursor()
            cur.execute("UPDATE oracle_stage9_pregame_lock SET slate_run_id='x' WHERE game_run_id=%s", (game,))
        c.rollback()
        with pytest.raises(psycopg2.Error):
            cur = c.cursor()
            cur.execute("DELETE FROM oracle_stage9_pregame_lock WHERE game_run_id=%s", (game,))
        c.rollback()
    finally:
        c.rollback(); c.close()


@_db
def test_kill_switch_disabled_raises_before_any_work():
    slate = "ORACLE-20260909-917"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        with pytest.raises(KillSwitchHaltError):
            run_stage_9(c, slate, [game], env=_DISABLED)
        assert _lock_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_rollback_and_no_false_success_on_persistence_failure():
    """Injected lifecycle-audit failure → whole stage rolls back and raises; nothing persists."""
    slate = "ORACLE-20260909-918"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-1", "S7F-a", _future_cutoff())
        c.commit()
        with patch.object(orchestrator, "_insert_lifecycle_audit", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                run_stage_9(c, slate, [game], env=_ENABLED)
        assert _lock_row(c, game) is None
        assert _game_status(c, game) == "activation_eligible"
        assert _slate_status(c, slate) == "activation_window_open"
        assert _play_locked_count(c, slate) == 0
    finally:
        c.rollback(); c.close()


# ===========================================================================
# C. Real independent-transaction slate-lock contention.
#
# Every case uses a manual HOLDER connection that holds the EXACT production slate-row lock
# (SELECT run_status FROM oracle_slate_runs WHERE slate_run_id=%s FOR UPDATE). The holder is
# released ONLY after a read-only observer PROVES, via pg_blocking_pids + pg_stat_activity, that
# the waiter's backend is blocked by the holder's backend on that lock while executing the slate
# FOR UPDATE query. Barrier/Event intent, a pre-run signal, or an arbitrary sleep are NOT used to
# establish contention — the observed lock state is. The real production lock/read/gate path in
# run_stage_9 is exercised (never mocked); only the clock is injected (cutoff cases) to make the
# post-wait decision time deterministic.
# ===========================================================================

class _MutableClock:
    """Injectable, thread-visible clock; run_stage_9 calls _now_utc() -> current .value."""
    def __init__(self, value):
        self.value = value
    def __call__(self):
        return self.value


def _connect_autocommit():
    c = _connect()
    c.autocommit = True
    return c


def _backend_pid(conn):
    cur = conn.cursor(); cur.execute("SELECT pg_backend_pid()"); pid = cur.fetchone()[0]; cur.close()
    return pid


def _hold_slate_lock(conn, slate):
    cur = conn.cursor()
    cur.execute("SELECT run_status FROM oracle_slate_runs WHERE slate_run_id=%s FOR UPDATE", (slate,))
    cur.fetchone(); cur.close()


def _blockers(observer, pid):
    cur = observer.cursor(); cur.execute("SELECT pg_blocking_pids(%s)", (pid,))
    arr = cur.fetchone()[0] or []; cur.close()
    return list(arr)


def _reaches_holder(observer, waiter_pid, holder_pid, max_nodes=32):
    seen = set(); stack = [waiter_pid]
    while stack and len(seen) < max_nodes:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        b = _blockers(observer, pid)
        if holder_pid in b:
            return True
        stack.extend(b)
    return False


def _await_blocked_on_slate(observer, waiter_pid, holder_pid, slate, deadline_s=20.0):
    end = time.monotonic() + deadline_s
    last = {}
    while time.monotonic() < end:
        cur = observer.cursor()
        cur.execute(
            "SELECT wait_event_type, state, query, pg_blocking_pids(%s) FROM pg_stat_activity WHERE pid=%s",
            (waiter_pid, waiter_pid),
        )
        row = cur.fetchone()
        cur.close()
        wait_type, state, query, blockers = (row if row else (None, None, None, None))
        q = (query or "")
        waiting_on_slate_lock = (wait_type == "Lock" and "for update" in q.lower() and slate in q)
        reaches = waiting_on_slate_lock and _reaches_holder(observer, waiter_pid, holder_pid)
        last = {"blocked_by_holder": bool(reaches), "wait_event_type": wait_type, "state": state,
                "query": q, "direct_blockers": list(blockers or [])}
        if reaches:
            return last
        time.sleep(0.05)
    raise AssertionError(
        f"waiter pid={waiter_pid} not proven blocked (transitively) by holder pid={holder_pid} on "
        f"the slate lock; last observation: {last}"
    )


def _spawn_waiter(slate, game, key, results, errors, pids):
    def run():
        c = _connect()
        try:
            cur = c.cursor(); cur.execute("SET lock_timeout = '25s'"); cur.close()
            pids[key] = _backend_pid(c)
            results[key] = run_stage_9(c, slate, [game], env=_ENABLED)
        except Exception as e:  # noqa: BLE001
            errors[key] = repr(e)
            try: c.rollback()
            except Exception: pass
        finally:
            c.close()
    t = threading.Thread(target=run); t.start(); return t


def _wait_pid(pids, key, deadline_s=10.0):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if key in pids:
            return pids[key]
        time.sleep(0.02)
    raise AssertionError(f"waiter '{key}' did not report its backend pid in time")


@_db
def test_contention_different_games_complete_slate_exactly_once():
    """Two waiters for DIFFERENT games are both proven blocked on the slate lock held by a manual
    holder; on release they serialize, both games lock, and the slate completes exactly once."""
    slate = "ORACLE-20260909-920"; g1 = f"{slate}-G1"; g2 = f"{slate}-G2"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, g1); _seed_admission(setup, slate, g1, "S8A-1", "S7F-1", _future_cutoff())
        _seed_game(setup, slate, g2); _seed_admission(setup, slate, g2, "S8A-2", "S7F-2", _future_cutoff())
        setup.commit()
    finally:
        setup.close()

    holder = _connect(); observer = _connect_autocommit()
    results, errors, pids = {}, {}, {}
    t1 = t2 = None
    try:
        holder_pid = _backend_pid(holder)
        _hold_slate_lock(holder, slate)
        t1 = _spawn_waiter(slate, g1, "a", results, errors, pids)
        t2 = _spawn_waiter(slate, g2, "b", results, errors, pids)
        ev1 = _await_blocked_on_slate(observer, _wait_pid(pids, "a"), holder_pid, slate)
        ev2 = _await_blocked_on_slate(observer, _wait_pid(pids, "b"), holder_pid, slate)
        assert ev1["blocked_by_holder"] and ev2["blocked_by_holder"]
        holder.rollback()                       # release AFTER both proven blocked (no lock)
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        for t in (t1, t2):
            if t is not None:
                t.join(timeout=30); assert not t.is_alive()
        observer.close()

    assert errors == {}, f"worker errors: {errors}"
    assert results["a"][0].outcome == s9.LOCKED
    assert results["b"][0].outcome == s9.LOCKED
    v = _connect()
    try:
        assert _slate_status(v, slate) == "pregame_locked"          # completed exactly once
        assert _lock_row(v, g1) is not None and _lock_row(v, g2) is not None
    finally:
        v.close()


@_db
def test_contention_same_game_predecessor_commit_is_historical_replay():
    """The waiter is proven blocked on the slate lock; the holder then COMMITS a lock for the game
    and releases. The waiter reconciles the committed lock historically → EXACT_REPLAY, without a
    second lock row."""
    slate = "ORACLE-20260909-921"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_admission(setup, slate, game, "S8A-1", "S7F-1", _future_cutoff())
        setup.commit()
    finally:
        setup.close()

    holder = _connect(); observer = _connect_autocommit()
    results, errors, pids = {}, {}, {}
    tw = None
    try:
        holder_pid = _backend_pid(holder)
        _hold_slate_lock(holder, slate)
        tw = _spawn_waiter(slate, game, "b", results, errors, pids)
        ev = _await_blocked_on_slate(observer, _wait_pid(pids, "b"), holder_pid, slate)
        assert ev["blocked_by_holder"]
        _seed_lock(holder, slate, game, "S8A-1", "S7F-1", _future_cutoff())   # committed predecessor
        holder.commit()                                                       # release + publish
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        if tw is not None:
            tw.join(timeout=30); assert not tw.is_alive()
        observer.close()

    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s9.EXACT_REPLAY
    v = _connect()
    try:
        cur = v.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage9_pregame_lock WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1                                         # exactly one lock
        cur.close()
        assert _divergence_audit_count(v, game) == 0
    finally:
        v.close()


@_db
def test_contention_predecessor_rollback_then_fresh_lock_succeeds():
    """The waiter is proven blocked; the holder rolls back (no lock) and releases. The waiter then
    performs fresh state/input/time checks and locks → LOCKED."""
    slate = "ORACLE-20260909-922"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_admission(setup, slate, game, "S8A-1", "S7F-1", _future_cutoff())
        setup.commit()
    finally:
        setup.close()

    holder = _connect(); observer = _connect_autocommit()
    results, errors, pids = {}, {}, {}
    tw = None
    try:
        holder_pid = _backend_pid(holder)
        _hold_slate_lock(holder, slate)
        tw = _spawn_waiter(slate, game, "b", results, errors, pids)
        ev = _await_blocked_on_slate(observer, _wait_pid(pids, "b"), holder_pid, slate)
        assert ev["blocked_by_holder"]
        holder.rollback()                       # release with NO lock persisted
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        if tw is not None:
            tw.join(timeout=30); assert not tw.is_alive()
        observer.close()

    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s9.LOCKED
    v = _connect()
    try:
        assert _lock_row(v, game) is not None
        assert _slate_status(v, slate) == "pregame_locked"
    finally:
        v.close()


def _run_cutoff_contention(slate, game, cutoff_at, post_wait_clock):
    """Shared driver: prove the waiter blocked pre-cutoff, then advance an injected clock to
    post_wait_clock BEFORE releasing the holder, and return the waiter's outcome. The waiter's
    fresh decision_time is sampled only AFTER acquiring the lock (post-wait), so it uses the
    advanced clock. Returns (results, errors)."""
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_admission(setup, slate, game, "S8A-1", "S7F-1", cutoff_at)
        setup.commit()
    finally:
        setup.close()

    clk = _MutableClock(cutoff_at - timedelta(minutes=1))     # pre-cutoff while blocked
    holder = _connect(); observer = _connect_autocommit()
    results, errors, pids = {}, {}, {}
    tw = None
    with patch("backend.oracle.orchestrator._now_utc", new=clk):
        try:
            holder_pid = _backend_pid(holder)
            _hold_slate_lock(holder, slate)
            tw = _spawn_waiter(slate, game, "b", results, errors, pids)
            ev = _await_blocked_on_slate(observer, _wait_pid(pids, "b"), holder_pid, slate)
            assert ev["blocked_by_holder"]
            clk.value = post_wait_clock          # advance the clock to/after cutoff before release
            holder.rollback()                    # release; waiter samples decision_time = clk.value
        finally:
            try: holder.rollback()
            except Exception: pass
            holder.close()
            if tw is not None:
                tw.join(timeout=30); assert not tw.is_alive()
            observer.close()
    return results, errors


@_db
def test_contention_post_wait_decision_equal_cutoff_rejects():
    """Blocked pre-cutoff; clock advanced to EXACTLY the cutoff before release → the post-wait
    decision (decision_time == cutoff) is not strictly before → INELIGIBLE, no lock."""
    slate = "ORACLE-20260909-926"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff)   # equality
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s9.INELIGIBLE and results["b"][0].reason == "at_or_after_cutoff"
    v = _connect()
    try:
        assert _lock_row(v, game) is None
        assert _slate_status(v, slate) == "activation_window_open"
    finally:
        v.close()


@_db
def test_contention_post_wait_decision_after_cutoff_rejects():
    """Blocked pre-cutoff; clock advanced to AFTER the cutoff before release → INELIGIBLE, no lock.
    Proves the decision uses the post-wait time, not the pre-wait time."""
    slate = "ORACLE-20260909-927"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff + timedelta(minutes=1))
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s9.INELIGIBLE and results["b"][0].reason == "at_or_after_cutoff"
    v = _connect()
    try:
        assert _lock_row(v, game) is None
        assert _slate_status(v, slate) == "activation_window_open"
    finally:
        v.close()


@_db
def test_contention_post_wait_decision_before_cutoff_locks():
    """Control: blocked pre-cutoff; clock left BEFORE the cutoff → the post-wait decision locks
    (LOCKED). Confirms the same proven-blocked path yields a lock when still in time."""
    slate = "ORACLE-20260909-928"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff - timedelta(seconds=30))
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s9.LOCKED
    v = _connect()
    try:
        assert _lock_row(v, game) is not None
        assert _slate_status(v, slate) == "pregame_locked"
    finally:
        v.close()


@_db
def test_contention_concurrent_divergence_writes_exactly_one_audit():
    """Two independent connections concurrently hit the same CHANGED_PROVENANCE; the advisory lock
    + re-read serialize the check+insert so exactly one divergence audit row is written."""
    slate = "ORACLE-20260909-924"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate, run_status="pregame_locked")
        _seed_game(setup, slate, game, status="pregame_locked")
        _seed_admission(setup, slate, game, "S8A-current", "S7F-current", _future_cutoff())
        _seed_lock(setup, slate, game, "S8A-OLD", "S7F-OLD", _future_cutoff())
        setup.commit()
    finally:
        setup.close()

    results, errors = {}, {}
    barrier = threading.Barrier(2)

    def worker(tag):
        c = _connect()
        try:
            cur = c.cursor(); cur.execute("SET lock_timeout = '20s'"); cur.close()
            barrier.wait()
            results[tag] = run_stage_9(c, slate, [game], env=_ENABLED)
            c.commit()
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
    assert results["a"][0].outcome == s9.CHANGED_PROVENANCE
    assert results["b"][0].outcome == s9.CHANGED_PROVENANCE
    v = _connect()
    try:
        assert _divergence_audit_count(v, game) == 1
    finally:
        v.close()


# ===========================================================================
# D. Defensive uniqueness recovery (SEPARATE from normal contention; unexpected 23505)
# ===========================================================================

class _FakeUnique(Exception):
    pgcode = "23505"


@_db
def test_defensive_unexpected_23505_with_committed_lock_reconciles_historically():
    """An unexpected 23505 on insert, with a verified committed lock on re-read, reconciles to
    EXACT_REPLAY via ROLLBACK TO SAVEPOINT + re-read (not a new lock)."""
    slate = "ORACLE-20260909-930"; game = f"{slate}-G1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-x", "S7F-x", _future_cutoff())
        c.commit()
        committed_lock = ("S9L-committed", "S8A-x", "S7F-x", _future_cutoff(), "before")
        with patch.object(orchestrator, "_fetch_stage9_lock", side_effect=[None, committed_lock]), \
             patch.object(orchestrator, "_insert_stage9_lock", side_effect=_FakeUnique()):
            res = run_stage_9(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s9.EXACT_REPLAY       # current S8A-x/S7F-x == committed
    finally:
        c.rollback(); c.close()


@_db
def test_defensive_unexpected_23505_with_no_lock_rolls_back_and_raises():
    """An unexpected 23505 with NO committed lock on re-read → Stage9LockError (no new-lock retry,
    uniqueness alone is never success)."""
    slate = "ORACLE-20260909-931"; game = f"{slate}-G1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S8A-x", "S7F-x", _future_cutoff())
        c.commit()
        with patch.object(orchestrator, "_fetch_stage9_lock", side_effect=[None, None]), \
             patch.object(orchestrator, "_insert_stage9_lock", side_effect=_FakeUnique()):
            with pytest.raises(Stage9LockError):
                run_stage_9(c, slate, [game], env=_ENABLED)
        c.rollback()
        assert _lock_row(c, game) is None
    finally:
        c.rollback(); c.close()
