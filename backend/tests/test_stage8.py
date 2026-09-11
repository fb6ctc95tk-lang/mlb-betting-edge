"""Oracle Stage 8 — Activation Window (C1 FULL) tests (PM-1067 / PM-1069 / PM-1071 / PM-1073).

Sections:
  A. Pure helper tests (no DB): activation identity, timestamp validity, strict before-cutoff
     gate, cutoff relationship.
  B. DB integration (requires ORACLE_TEST_DATABASE_URL): first admission, ineligible variants,
     unavailable/missing evidence, historical replay, changed provenance (+ dedup), mixed /
     zero-eligible / empty slates, later admission, advanced-state rejection, cutoff future/past,
     immutability, zero Stage-8 events, rollback / no false success.
  C. Real independent-transaction slate-lock contention: different games open the slate once;
     same-game predecessor commit → historical replay; same-game predecessor rollback → fresh
     checks (success, and after-cutoff → no admission); concurrent divergence dedup.
  D. Defensive uniqueness recovery (kept SEPARATE from normal contention): unexpected 23505 with
     a verified committed admission → historical reconciliation; with none → rollback-and-raise.

Historical backend baseline is 806 passed / 4 skipped / 0 failed; these tests are additive.
Stage 8 admission is procedural only: no bet, edge, official confirmation, source freshness, or
betting readiness; it binds only the frozen Stage 7 evidence and revalidates no live input.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.oracle import stage8_activation as s8
from backend.oracle import orchestrator
from backend.oracle.orchestrator import (
    KillSwitchHaltError,
    Stage8ActivationError,
    run_stage_8,
)

_ENABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "true"}
_DISABLED = {"ORACLE_AUTONOMOUS_RUN_ENABLED": "false"}


def _aware(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ===========================================================================
# A. Pure helper tests (no DB)
# ===========================================================================

def test_activation_identity_is_deterministic_and_prefixed():
    a = s8.compute_activation_identity("G", "S7F-G-abc123")
    b = s8.compute_activation_identity("G", "S7F-G-abc123")
    assert a == b
    assert a.startswith("S8A-G-")


def test_activation_identity_changes_with_stage7_identity_only():
    ref = s8.compute_activation_identity("G", "S7F-G-aaa")
    assert s8.compute_activation_identity("G", "S7F-G-bbb") != ref   # different frozen evidence
    assert s8.compute_activation_identity("H", "S7F-G-aaa") != ref   # different game


def test_is_timezone_aware():
    assert s8.is_timezone_aware(_aware(2026, 9, 11, 12))
    assert not s8.is_timezone_aware(datetime(2026, 9, 11, 12))       # naive
    assert not s8.is_timezone_aware("2026-09-11T12:00:00Z")          # not a datetime
    assert not s8.is_timezone_aware(None)


def test_is_before_cutoff_is_strict():
    decision = _aware(2026, 9, 11, 12, 0)
    assert s8.is_before_cutoff(decision, _aware(2026, 9, 11, 12, 1))       # before → True
    assert not s8.is_before_cutoff(decision, _aware(2026, 9, 11, 12, 0))   # equal → False (rejects)
    assert not s8.is_before_cutoff(decision, _aware(2026, 9, 11, 11, 59))  # after → False


def test_is_before_cutoff_false_for_naive_or_missing():
    decision = _aware(2026, 9, 11, 12, 0)
    assert not s8.is_before_cutoff(decision, datetime(2026, 9, 11, 13))    # naive cutoff
    assert not s8.is_before_cutoff(datetime(2026, 9, 11, 12), _aware(2026, 9, 11, 13))  # naive decision
    assert not s8.is_before_cutoff(decision, None)


def test_cutoff_relationship_classification():
    decision = _aware(2026, 9, 11, 12, 0)
    assert s8.cutoff_relationship(decision, _aware(2026, 9, 11, 12, 5)) == s8.CUTOFF_BEFORE
    assert s8.cutoff_relationship(decision, _aware(2026, 9, 11, 12, 0)) == s8.CUTOFF_EQUAL
    assert s8.cutoff_relationship(decision, _aware(2026, 9, 11, 11, 0)) == s8.CUTOFF_AFTER
    assert s8.cutoff_relationship(decision, None) is None


def test_membership_reason_code_is_bounded():
    assert s8.REASON_NOT_IN_SLATE == "not_in_slate"


def test_standing_limitations_are_honest_and_non_empty():
    lims = s8.standing_limitations()
    assert "procedural_admission_only_not_a_play" in lims
    assert "not_source_freshness_or_betting_readiness" in lims
    assert "historical_admission_not_perpetual_permission_after_cutoff" in lims


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


def _seed_slate(conn, slate, run_status="analysis_in_progress"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_slate_runs (slate_run_id, run_date, run_status, run_started_at) "
        "VALUES (%s, '2026-09-09', %s, NOW()) ON CONFLICT DO NOTHING",
        (slate, run_status),
    )
    cur.close()


def _seed_game(conn, slate, game, status="final_analysis"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO oracle_game_analyses "
        "(game_run_id, slate_run_id, external_game_id, home_team, away_team, first_pitch_time, game_status) "
        "VALUES (%s, %s, '746484', 'BOS', 'NYY', '2026-09-09T23:20:00+00:00', %s) ON CONFLICT DO NOTHING",
        (game, slate, status),
    )
    cur.close()


def _seed_frozen7(conn, slate, game, identity, cutoff_at, s5id=None):
    """Insert a frozen Stage-7 record directly (to make a game Stage-8-eligible)."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO oracle_stage7_final_analysis
            (game_run_id, slate_run_id, stage5_result_id, data_version_id, policy_version_id,
             verdict, scheduled_cutoff_at, stage6_snapshot_identity, stage6_observed_at,
             cutoff_relationship, bound_input_identity, limitations, assessment_at)
        VALUES (%s,%s,%s,'DV-1','MLB-A3-v1','LEAN_HOME',%s,'S6O-x',%s,'before',%s,'[]'::jsonb, NOW())
        ON CONFLICT DO NOTHING
        """,
        (game, slate, s5id or f"S5R-{game}", cutoff_at, _aware(2026, 9, 9, 22, 0), identity),
    )
    cur.close()


def _seed_admission(conn, slate, game, stage7_identity, cutoff_at, activation_identity=None):
    """Insert a Stage-8 admission row directly (to construct post-admission states)."""
    cur = conn.cursor()
    act = activation_identity or s8.compute_activation_identity(game, stage7_identity)
    cur.execute(
        """
        INSERT INTO oracle_stage8_activation_window
            (game_run_id, slate_run_id, stage7_bound_input_identity, activation_identity,
             scheduled_cutoff_at, cutoff_relationship, limitations, assessment_at)
        VALUES (%s,%s,%s,%s,%s,'before','[]'::jsonb, NOW())
        ON CONFLICT DO NOTHING
        """,
        (game, slate, stage7_identity, act, cutoff_at),
    )
    cur.close()


def _admission_row(conn, game):
    cur = conn.cursor()
    cur.execute(
        "SELECT activation_identity, stage7_bound_input_identity, cutoff_relationship "
        "FROM oracle_stage8_activation_window WHERE game_run_id=%s",
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
        "SELECT COUNT(*) FROM oracle_lifecycle_audit WHERE game_run_id=%s AND stage='8' "
        "AND event='stage8_activation_divergence'", (game,))
    n = cur.fetchone()[0]
    cur.close()
    return n


def _event_count(conn, slate):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM oracle_play_events WHERE slate_run_id=%s", (slate,))
    n = cur.fetchone()[0]
    cur.close()
    return n


@_db
def test_first_admission_window_opened():
    slate = "ORACLE-20260909-801"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        before = _event_count(c, slate)
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert len(res) == 1 and res[0].outcome == s8.WINDOW_OPENED
        assert res[0].cutoff_relationship == "before"
        assert _game_status(c, game) == "activation_eligible"
        assert _slate_status(c, slate) == "activation_window_open"
        row = _admission_row(c, game)
        assert row is not None and row[1] == "S7F-a"
        assert _event_count(c, slate) == before            # C3: zero Stage-8 events
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_not_in_final_analysis():
    slate = "ORACLE-20260909-802"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game, status="lineup_monitoring")
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "not_in_final_analysis"
        assert _admission_row(c, game) is None
        assert _slate_status(c, slate) == "analysis_in_progress"   # zero-eligible → no open
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_no_stage7_record():
    slate = "ORACLE-20260909-803"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)   # no frozen Stage-7 record
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "no_stage7_final_record"
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_membership_foreign_slate_rejected_without_writes():
    """A game whose persisted slate_run_id != the locked slate is rejected (not_in_slate) with no
    admission, no transition, no audit, and no change to the foreign game (PM-1075)."""
    s_true = "ORACLE-20260909-816"; s_other = "ORACLE-20260909-817"
    game = f"{s_true}-BOS-NYY-1"                       # persisted under s_true
    c = _connect()
    try:
        _seed_slate(c, s_true); _seed_slate(c, s_other)
        _seed_game(c, s_true, game)                    # game.slate_run_id = s_true
        _seed_frozen7(c, s_true, game, "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_8(c, s_other, [game], env=_ENABLED)   # locked slate = s_other (foreign)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "not_in_slate"
        assert _admission_row(c, game) is None                # no admission created
        assert _game_status(c, game) == "final_analysis"      # foreign game untouched
        assert _slate_status(c, s_other) == "analysis_in_progress"  # foreign slate not opened
        assert _slate_status(c, s_true) == "analysis_in_progress"   # true slate not opened
        assert _divergence_audit_count(c, game) == 0
    finally:
        c.rollback(); c.close()


@_db
def test_membership_missing_game_row_rejected():
    """A game_run_id with no persisted oracle_game_analyses row → not_in_slate, no writes."""
    slate = "ORACLE-20260909-818"; game = f"{slate}-DOES-NOT-EXIST"
    c = _connect()
    try:
        _seed_slate(c, slate); c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "not_in_slate"
        assert _admission_row(c, game) is None
        assert _slate_status(c, slate) == "analysis_in_progress"
    finally:
        c.rollback(); c.close()


@_db
def test_membership_existing_foreign_admission_not_reconciled():
    """An existing admission for a game belonging to another slate is NOT reconciled as belonging
    to the supplied slate: the membership boundary is enforced BEFORE existence-first reconciliation,
    so no EXACT_REPLAY/CHANGED_PROVENANCE is produced and neither slate/admission/audit mutates."""
    s_true = "ORACLE-20260909-819"; s_other = "ORACLE-20260909-825"
    game = f"{s_true}-BOS-NYY-1"                       # persisted under s_true
    c = _connect()
    try:
        _seed_slate(c, s_true); _seed_slate(c, s_other)
        _seed_game(c, s_true, game)
        _seed_frozen7(c, s_true, game, "S7F-current", _future_cutoff())
        _seed_admission(c, s_true, game, "S7F-current", _future_cutoff())   # committed foreign admission
        c.commit()
        before = _admission_row(c, game)
        res = run_stage_8(c, s_other, [game], env=_ENABLED)   # foreign locked slate
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "not_in_slate"
        # admission row unchanged (still bound to its original identity); no divergence audit
        assert _admission_row(c, game) == before
        assert _divergence_audit_count(c, game) == 0
        assert _slate_status(c, s_other) == "analysis_in_progress"
    finally:
        c.rollback(); c.close()


@_db
def test_ineligible_after_cutoff():
    slate = "ORACLE-20260909-804"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _past_cutoff())   # cutoff already passed
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "at_or_after_cutoff"
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_advanced_slate_rejects_new_admission():
    slate = "ORACLE-20260909-805"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate, run_status="pregame_locked")
        _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.INELIGIBLE and res[0].reason == "slate_not_open_for_admission"
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_later_admission_while_window_open_does_not_reopen():
    slate = "ORACLE-20260909-806"; game = f"{slate}-BOS-NYY-2"
    c = _connect()
    try:
        _seed_slate(c, slate, run_status="activation_window_open")   # already open
        _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.WINDOW_OPENED
        assert _game_status(c, game) == "activation_eligible"
        assert _slate_status(c, slate) == "activation_window_open"   # unchanged, not re-transitioned
    finally:
        c.rollback(); c.close()


@_db
def test_empty_slate_does_not_open():
    slate = "ORACLE-20260909-807"
    c = _connect()
    try:
        _seed_slate(c, slate); c.commit()
        res = run_stage_8(c, slate, [], env=_ENABLED)
        assert res == []
        assert _slate_status(c, slate) == "analysis_in_progress"
    finally:
        c.rollback(); c.close()


@_db
def test_mixed_slate_opens_once_and_classifies_independently():
    slate = "ORACLE-20260909-808"
    g_ok = f"{slate}-OK-1"; g_bad = f"{slate}-BAD-2"
    c = _connect()
    try:
        _seed_slate(c, slate)
        _seed_game(c, slate, g_ok); _seed_frozen7(c, slate, g_ok, "S7F-ok", _future_cutoff())
        _seed_game(c, slate, g_bad, status="lineup_monitoring")
        c.commit()
        res = {r.game_run_id: r for r in run_stage_8(c, slate, [g_ok, g_bad], env=_ENABLED)}
        assert res[g_ok].outcome == s8.WINDOW_OPENED
        assert res[g_bad].outcome == s8.INELIGIBLE
        assert _slate_status(c, slate) == "activation_window_open"   # opened because >=1 qualified
        assert _admission_row(c, g_ok) is not None
        assert _admission_row(c, g_bad) is None
    finally:
        c.rollback(); c.close()


@_db
def test_exact_replay_is_read_only():
    slate = "ORACLE-20260909-809"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        run_stage_8(c, slate, [game], env=_ENABLED)          # WINDOW_OPENED
        res = run_stage_8(c, slate, [game], env=_ENABLED)    # re-invoke
        assert res[0].outcome == s8.EXACT_REPLAY
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage8_activation_window WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1                        # no second row
        cur.close()
        assert _divergence_audit_count(c, game) == 0
    finally:
        c.rollback(); c.close()


@_db
def test_changed_provenance_writes_one_dedup_audit_and_preserves_row():
    slate = "ORACLE-20260909-810"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        # current frozen evidence identity = S7F-current; admitted against an OLD identity
        _seed_frozen7(c, slate, game, "S7F-current", _future_cutoff())
        _seed_admission(c, slate, game, "S7F-OLD", _future_cutoff())
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.CHANGED_PROVENANCE
        assert res[0].differing_inputs == ("stage7_bound_input_identity",)
        assert _divergence_audit_count(c, game) == 1
        # re-invoke: dedup → still exactly one divergence row
        run_stage_8(c, slate, [game], env=_ENABLED)
        assert _divergence_audit_count(c, game) == 1
        assert _admission_row(c, game)[1] == "S7F-OLD"       # admission row unchanged
    finally:
        c.rollback(); c.close()


@_db
def test_unavailable_inputs_when_frozen_record_missing_after_admission():
    slate = "ORACLE-20260909-811"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_admission(c, slate, game, "S7F-a", _future_cutoff())   # admission but NO frozen record
        c.commit()
        res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.UNAVAILABLE_INPUTS
        assert res[0].reason == "unreadable_comparison_inputs"
        assert _admission_row(c, game) is not None                    # preserved
        assert _divergence_audit_count(c, game) == 0
    finally:
        c.rollback(); c.close()


@_db
def test_cutoff_missing_or_invalid_yields_unavailable_inputs():
    """Defensive: a non-tz-aware frozen cutoff maps to UNAVAILABLE_INPUTS (no admission)."""
    slate = "ORACLE-20260909-812"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        naive_row = ("S7F-a", "S5R", "DV-1", "MLB-A3-v1",
                     datetime(2026, 12, 1, 0, 0), "S6O-x", "LEAN_HOME")  # naive cutoff at idx 4
        with patch.object(orchestrator, "_fetch_stage7_final", return_value=naive_row):
            res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.UNAVAILABLE_INPUTS
        assert res[0].reason == "cutoff_missing_or_invalid"
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_admission_row_is_immutable():
    slate = "ORACLE-20260909-813"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        run_stage_8(c, slate, [game], env=_ENABLED)
        import psycopg2
        with pytest.raises(psycopg2.Error):
            cur = c.cursor()
            cur.execute("UPDATE oracle_stage8_activation_window SET slate_run_id='x' WHERE game_run_id=%s", (game,))
        c.rollback()
        with pytest.raises(psycopg2.Error):
            cur = c.cursor()
            cur.execute("DELETE FROM oracle_stage8_activation_window WHERE game_run_id=%s", (game,))
        c.rollback()
    finally:
        c.rollback(); c.close()


@_db
def test_kill_switch_disabled_raises_before_any_work():
    slate = "ORACLE-20260909-814"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        with pytest.raises(KillSwitchHaltError):
            run_stage_8(c, slate, [game], env=_DISABLED)
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()


@_db
def test_rollback_and_no_false_success_on_persistence_failure():
    """Injected lifecycle-audit failure → whole stage rolls back and raises; nothing persists."""
    slate = "ORACLE-20260909-815"; game = f"{slate}-BOS-NYY-1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-a", _future_cutoff())
        c.commit()
        with patch.object(orchestrator, "_insert_lifecycle_audit", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                run_stage_8(c, slate, [game], env=_ENABLED)
        # after rollback the connection is usable and nothing was committed
        assert _admission_row(c, game) is None
        assert _game_status(c, game) == "final_analysis"
        assert _slate_status(c, slate) == "analysis_in_progress"
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
# run_stage_8 is exercised (never mocked); only the clock is injected (cutoff cases) to make the
# post-wait decision time deterministic.
# ===========================================================================

class _MutableClock:
    """Injectable, thread-visible clock; run_stage_8 calls _now_utc() -> current .value."""
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
    """Acquire and hold the exact production slate-row FOR UPDATE lock (caller commits/rolls back)."""
    cur = conn.cursor()
    cur.execute("SELECT run_status FROM oracle_slate_runs WHERE slate_run_id=%s FOR UPDATE", (slate,))
    cur.fetchone(); cur.close()


def _blockers(observer, pid):
    cur = observer.cursor(); cur.execute("SELECT pg_blocking_pids(%s)", (pid,))
    arr = cur.fetchone()[0] or []; cur.close()
    return list(arr)


def _reaches_holder(observer, waiter_pid, holder_pid, max_nodes=32):
    """True iff holder_pid is reachable from waiter_pid by transitively following pg_blocking_pids
    (holder holds the row lock; earlier waiters in the queue may sit between them)."""
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
    """Poll (read-only) until the waiter is waiting on a Lock while running the slate FOR UPDATE
    query AND holder_pid is (transitively) among its blockers via pg_blocking_pids. Returns an
    evidence dict; raises AssertionError with diagnostics on timeout. Deterministic contention proof
    (transitive because a second waiter may queue behind the first, which queues behind the holder)."""
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
    """Start a thread that captures its backend pid then runs run_stage_8([game]); bounded by
    lock_timeout so a broken design errors rather than hangs. Returns the Thread."""
    def run():
        c = _connect()
        try:
            cur = c.cursor(); cur.execute("SET lock_timeout = '25s'"); cur.close()
            pids[key] = _backend_pid(c)
            results[key] = run_stage_8(c, slate, [game], env=_ENABLED)
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
def test_contention_different_games_open_slate_exactly_once():
    """Two waiters for DIFFERENT games are both proven blocked on the slate lock held by a manual
    holder; on release they serialize so the slate opens exactly once and both games are admitted."""
    slate = "ORACLE-20260909-820"; g1 = f"{slate}-G1"; g2 = f"{slate}-G2"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, g1); _seed_frozen7(setup, slate, g1, "S7F-1", _future_cutoff())
        _seed_game(setup, slate, g2); _seed_frozen7(setup, slate, g2, "S7F-2", _future_cutoff())
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
        holder.rollback()                       # release AFTER both proven blocked (no admission)
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        for t in (t1, t2):
            if t is not None:
                t.join(timeout=30); assert not t.is_alive()
        observer.close()

    assert errors == {}, f"worker errors: {errors}"
    assert results["a"][0].outcome == s8.WINDOW_OPENED
    assert results["b"][0].outcome == s8.WINDOW_OPENED
    v = _connect()
    try:
        assert _slate_status(v, slate) == "activation_window_open"   # opened exactly once
        assert _admission_row(v, g1) is not None and _admission_row(v, g2) is not None
    finally:
        v.close()


@_db
def test_contention_same_game_predecessor_commit_is_historical_replay():
    """The waiter is proven blocked on the slate lock; the holder then COMMITS an admission for the
    game and releases. The waiter reconciles the committed admission historically → EXACT_REPLAY,
    without re-gating the cutoff and without a second admission row."""
    slate = "ORACLE-20260909-821"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_frozen7(setup, slate, game, "S7F-1", _future_cutoff())
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
        _seed_admission(holder, slate, game, "S7F-1", _future_cutoff())   # committed predecessor
        holder.commit()                                                   # release + publish
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        if tw is not None:
            tw.join(timeout=30); assert not tw.is_alive()
        observer.close()

    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s8.EXACT_REPLAY
    v = _connect()
    try:
        cur = v.cursor()
        cur.execute("SELECT COUNT(*) FROM oracle_stage8_activation_window WHERE game_run_id=%s", (game,))
        assert cur.fetchone()[0] == 1                                     # exactly one admission
        cur.close()
        assert _divergence_audit_count(v, game) == 0
    finally:
        v.close()


@_db
def test_contention_predecessor_rollback_then_fresh_admission_succeeds():
    """The waiter is proven blocked on the slate lock; the holder rolls back (no admission) and
    releases. The waiter then performs fresh state/input/time checks and admits → WINDOW_OPENED."""
    slate = "ORACLE-20260909-822"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_frozen7(setup, slate, game, "S7F-1", _future_cutoff())
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
        holder.rollback()                       # release with NO admission persisted
    finally:
        try: holder.rollback()
        except Exception: pass
        holder.close()
        if tw is not None:
            tw.join(timeout=30); assert not tw.is_alive()
        observer.close()

    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s8.WINDOW_OPENED
    v = _connect()
    try:
        assert _admission_row(v, game) is not None
        assert _slate_status(v, slate) == "activation_window_open"
    finally:
        v.close()


def _run_cutoff_contention(slate, game, cutoff_at, post_wait_clock):
    """Shared driver: prove the waiter blocked pre-cutoff, then advance an injected clock to
    post_wait_clock BEFORE releasing the holder, and return the waiter's outcome. The waiter's
    fresh decision_time is sampled only AFTER acquiring the lock (post-wait), so it uses the
    advanced clock. Returns (result, errors)."""
    setup = _connect()
    try:
        _seed_slate(setup, slate)
        _seed_game(setup, slate, game); _seed_frozen7(setup, slate, game, "S7F-1", cutoff_at)
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
    decision (decision_time == cutoff) is not strictly before → INELIGIBLE, no admission."""
    slate = "ORACLE-20260909-826"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff)   # equality
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s8.INELIGIBLE and results["b"][0].reason == "at_or_after_cutoff"
    v = _connect()
    try:
        assert _admission_row(v, game) is None
        assert _slate_status(v, slate) == "analysis_in_progress"
    finally:
        v.close()


@_db
def test_contention_post_wait_decision_after_cutoff_rejects():
    """Blocked pre-cutoff; clock advanced to AFTER the cutoff before release → INELIGIBLE, no
    admission. Proves the decision uses the post-wait time, not the pre-wait time."""
    slate = "ORACLE-20260909-827"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff + timedelta(minutes=1))
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s8.INELIGIBLE and results["b"][0].reason == "at_or_after_cutoff"
    v = _connect()
    try:
        assert _admission_row(v, game) is None
        assert _slate_status(v, slate) == "analysis_in_progress"
    finally:
        v.close()


@_db
def test_contention_post_wait_decision_before_cutoff_admits():
    """Control: blocked pre-cutoff; clock left BEFORE the cutoff → the post-wait decision admits
    (WINDOW_OPENED). Confirms the same proven-blocked path yields admission when still in time."""
    slate = "ORACLE-20260909-828"; game = f"{slate}-G1"
    cutoff = _aware(2026, 9, 20, 0, 0)
    results, errors = _run_cutoff_contention(slate, game, cutoff, cutoff - timedelta(seconds=30))
    assert errors == {}, f"errors: {errors}"
    assert results["b"][0].outcome == s8.WINDOW_OPENED
    v = _connect()
    try:
        assert _admission_row(v, game) is not None
        assert _slate_status(v, slate) == "activation_window_open"
    finally:
        v.close()


@_db
def test_contention_concurrent_divergence_writes_exactly_one_audit():
    """Two independent connections concurrently hit the same CHANGED_PROVENANCE; the advisory
    lock + re-read serialize the check+insert so exactly one divergence audit row is written."""
    slate = "ORACLE-20260909-824"; game = f"{slate}-G1"
    setup = _connect()
    try:
        _seed_slate(setup, slate, run_status="activation_window_open")
        _seed_game(setup, slate, game, status="activation_eligible")
        _seed_frozen7(setup, slate, game, "S7F-current", _future_cutoff())
        _seed_admission(setup, slate, game, "S7F-OLD", _future_cutoff())
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
            results[tag] = run_stage_8(c, slate, [game], env=_ENABLED)
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
    assert results["a"][0].outcome == s8.CHANGED_PROVENANCE
    assert results["b"][0].outcome == s8.CHANGED_PROVENANCE
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
def test_defensive_unexpected_23505_with_committed_admission_reconciles_historically():
    """An unexpected 23505 on insert, with a verified committed admission on re-read, reconciles
    to EXACT_REPLAY via ROLLBACK TO SAVEPOINT + re-read (not a new admission)."""
    slate = "ORACLE-20260909-830"; game = f"{slate}-G1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-x", _future_cutoff())
        c.commit()
        committed_row = ("S8A-committed", "S7F-x", _future_cutoff(), "before")
        with patch.object(orchestrator, "_fetch_stage8_activation", side_effect=[None, committed_row]), \
             patch.object(orchestrator, "_insert_stage8_activation", side_effect=_FakeUnique()):
            res = run_stage_8(c, slate, [game], env=_ENABLED)
        assert res[0].outcome == s8.EXACT_REPLAY       # current S7F-x == committed S7F-x
    finally:
        c.rollback(); c.close()


@_db
def test_defensive_unexpected_23505_with_no_admission_rolls_back_and_raises():
    """An unexpected 23505 with NO committed admission on re-read → Stage8ActivationError (no
    new-admission retry, uniqueness alone is never success)."""
    slate = "ORACLE-20260909-831"; game = f"{slate}-G1"
    c = _connect()
    try:
        _seed_slate(c, slate); _seed_game(c, slate, game)
        _seed_frozen7(c, slate, game, "S7F-x", _future_cutoff())
        c.commit()
        with patch.object(orchestrator, "_fetch_stage8_activation", side_effect=[None, None]), \
             patch.object(orchestrator, "_insert_stage8_activation", side_effect=_FakeUnique()):
            with pytest.raises(Stage8ActivationError):
                run_stage_8(c, slate, [game], env=_ENABLED)
        c.rollback()
        assert _admission_row(c, game) is None
    finally:
        c.rollback(); c.close()
