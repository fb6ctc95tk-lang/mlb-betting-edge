"""Oracle Phase 1 — Run Orchestrator (WP-4 T05–T08).

Coordinates the Phase 1 Oracle slate run lifecycle across Stages 1–10.
Stage 3 and Stages 5–10 are Phase 1 stubs that write approved event types and
transition state machines; they do not call providers, engines, or LLMs.
Stage 4 is a full Inc-2 implementation (Structural ECF v1; authorized PM-867).

CONNECTION AND TRANSACTION MODEL (DCR-W5-001 §6-8, DCR-W4-005):
  - The Orchestrator opens psycopg2 connections with autocommit=False.
  - The Orchestrator owns every transaction: it calls conn.commit() and
    conn.rollback(). WP-3 and WP-5 functions create and close cursors only.
  - Stage 1 atomicity: advisory lock + SELECT + INSERT oracle_slate_runs +
    INSERT slate_initialized event + UPDATE run_status='schedule_loaded'
    all execute within one transaction (DCR-W5-001 §10).
  - Stages 2–10 each own their own transaction: the Orchestrator commits
    after all DB operations for that stage succeed.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from backend.oracle.event_store import record_event
from backend.oracle.stage4_ecf import compute_ecf
from backend.oracle.fixtures import (
    get_game_pk,
    load_phase1_fixtures,
    validate_fixture_record,
)
from backend.oracle.identifier_manager import (
    generate_game_run_id,
    generate_slate_run_id,
)
from backend.oracle.kill_switch import is_autonomous_run_enabled
from backend.oracle.mlb_adapter import (
    LINEUP_OBSERVED_FULL,
    LINEUP_PARTIAL,
    MLBAdapter,
)
from backend.oracle.mlb_intelligence import GameEngineInput
from backend.oracle.sport_policy_store import PolicyReadOutcome
from backend.oracle.sport_policy_store_db import MLBSportPolicyStore
from backend.oracle.stage3_data_gather import gather_preliminary_data
from backend.oracle.stage5_pipeline import run_stage5_pipeline
from backend.oracle.stage6_lineup import (
    Stage6Result,
    canonical_from_stored,
    canonical_snapshot,
    compute_snapshot_identity,
    detect_material_change,
)
from backend.oracle import stage7_final_analysis as s7
from backend.oracle.state_machines import (
    transition_game_state,
    transition_slate_state,
)

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Base class for all Orchestrator errors."""


class KillSwitchHaltError(OrchestratorError):
    """Raised when ORACLE_AUTONOMOUS_RUN_ENABLED is false or absent at a stage gate."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _check_kill_switch(env: dict | None = None) -> None:
    """Raise KillSwitchHaltError if autonomous runs are not enabled."""
    if not is_autonomous_run_enabled(env=env):
        raise KillSwitchHaltError(
            "ORACLE_AUTONOMOUS_RUN_ENABLED is not true; autonomous stage halted"
        )


def _update_slate_status(conn: object, slate_run_id: str, new_status: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE oracle_slate_runs SET run_status = %s WHERE slate_run_id = %s",
            (new_status, slate_run_id),
        )
    finally:
        cur.close()


def _update_game_status(conn: object, game_run_id: str, new_status: str) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE oracle_game_analyses SET game_status = %s WHERE game_run_id = %s",
            (new_status, game_run_id),
        )
    finally:
        cur.close()


def _insert_preliminary_data(
    conn: object,
    game_run_id: str,
    slate_run_id: str,
    data_version_id: str,
    game_id: str,
    gathered_at: object,
    raw_payload: str,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_preliminary_data
                (game_run_id, slate_run_id, data_version_id, game_id,
                 gathered_at, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (game_run_id, slate_run_id, data_version_id, game_id,
             gathered_at, raw_payload),
        )
    finally:
        cur.close()


def _insert_lifecycle_audit(
    conn: object,
    game_run_id: str,
    slate_run_id: str,
    stage: str,
    event: str,
    detail: str | None = None,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_lifecycle_audit
                (game_run_id, slate_run_id, stage, event, detail)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (game_run_id, slate_run_id, stage, event, detail),
        )
    finally:
        cur.close()


def _fetch_preliminary_record(
    conn: object,
    game_run_id: str,
) -> tuple[object, str, object] | None:
    """Return (raw_payload, data_version_id, gathered_at) for game_run_id, or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT raw_payload, data_version_id, gathered_at
            FROM oracle_preliminary_data
            WHERE game_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _insert_ecf_result(
    conn: object,
    ecf_result_id: str,
    game_run_id: str,
    data_version_id: str,
    ecf_score: float,
    component_scores: dict,
    model_version: str,
    computed_at: object,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_ecf_results
                (ecf_result_id, game_run_id, data_version_id, ecf_score,
                 component_scores, model_version, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (ecf_result_id, game_run_id, data_version_id, ecf_score,
             json.dumps(component_scores), model_version, computed_at),
        )
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Stage 1 — Slate Initialization
# ---------------------------------------------------------------------------

def run_stage_1(
    conn: object,
    current_date_et: date,
    env: dict | None = None,
) -> str:
    """Stage 1 — Slate Initialization.

    Atomic transaction (DCR-W5-001 §10):
      1. pg_advisory_xact_lock + SELECT COUNT to generate Slate Run ID (WP-3)
      2. INSERT oracle_slate_runs with run_status='initializing'
      3. INSERT slate_initialized event (WP-5)
      4. transition_slate_state initializing → schedule_loaded (state machine)
      5. UPDATE oracle_slate_runs SET run_status='schedule_loaded'
      6. conn.commit()

    Kill switch is checked before any DB operation. On any exception, the
    caller must call conn.rollback() to prevent partial records.

    Args:
        conn: psycopg2 connection with autocommit=False. Caller owns lifecycle.
        current_date_et: America/Toronto business date for this slate run.
        env: Optional env dict for kill switch injection (tests only).

    Returns:
        The generated Slate Run ID string.

    Raises:
        KillSwitchHaltError: If ORACLE_AUTONOMOUS_RUN_ENABLED is not true.
        Any exception from WP-3 or WP-5 propagates unchanged; caller rolls back.
    """
    _check_kill_switch(env=env)

    slate_run_id = generate_slate_run_id(current_date_et, conn)
    run_started_at = _now_utc()

    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_slate_runs
                (slate_run_id, run_date, run_status, daily_plays_activated,
                 run_started_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (slate_run_id, current_date_et, "initializing", 0, run_started_at),
        )
    finally:
        cur.close()

    record_event(conn, "slate_initialized", slate_run_id, run_started_at)

    transition_slate_state("initializing", "schedule_loaded")
    _update_slate_status(conn, slate_run_id, "schedule_loaded")

    conn.commit()
    logger.info("Stage 1 complete: slate_run_id=%s", slate_run_id)
    return slate_run_id


# ---------------------------------------------------------------------------
# Stage 2 — Schedule Retrieval (fixture-based; no live provider)
# ---------------------------------------------------------------------------

def run_stage_2(
    conn: object,
    slate_run_id: str,
    env: dict | None = None,
) -> list[str]:
    """Stage 2 — Schedule Retrieval (fixture-based; no live MLB Stats API call).

    Creates one oracle_game_analyses record per fixture game, writes
    schedule_retrieved and game_analysis_started events, and transitions
    the slate from schedule_loaded to analysis_in_progress.

    Args:
        conn: psycopg2 connection with autocommit=False.
        slate_run_id: Slate Run ID from Stage 1.
        env: Optional env dict for kill switch injection.

    Returns:
        List of game_run_id strings, one per fixture game.

    Raises:
        KillSwitchHaltError: If kill switch is inactive.
    """
    _check_kill_switch(env=env)

    fixtures = load_phase1_fixtures()
    now = _now_utc()
    game_run_ids: list[str] = []

    for record in fixtures:
        validate_fixture_record(record)
        game_pk = get_game_pk(record)
        game_run_id = generate_game_run_id(
            slate_run_id,
            record["away_team"],
            record["home_team"],
            game_pk,
        )

        first_pitch_dt = datetime.fromisoformat(
            record["first_pitch_time"].replace("Z", "+00:00")
        )

        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO oracle_game_analyses
                    (game_run_id, slate_run_id, external_game_id,
                     home_team, away_team, first_pitch_time,
                     game_status, venue)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    game_run_id,
                    slate_run_id,
                    record["external_game_id"],
                    record["home_team"],
                    record["away_team"],
                    first_pitch_dt,
                    "scheduled",
                    record["venue"],
                ),
            )
        finally:
            cur.close()

        game_run_ids.append(game_run_id)

    record_event(conn, "schedule_retrieved", slate_run_id, now)

    for game_run_id in game_run_ids:
        record_event(
            conn, "game_analysis_started", slate_run_id, now,
            game_run_id=game_run_id,
        )

    transition_slate_state("schedule_loaded", "analysis_in_progress")
    _update_slate_status(conn, slate_run_id, "analysis_in_progress")

    conn.commit()
    logger.info("Stage 2 complete: %d game records created", len(game_run_ids))
    return game_run_ids


# ---------------------------------------------------------------------------
# Stage 3 — Preliminary Data Gather (Inc-1 implementation)
# ---------------------------------------------------------------------------

def run_stage_3(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 3 — Preliminary Data Gather (Inc-1; authorized by PM-785/Authorities A+B).

    MI-5 gate: adapter.get_availability() is called before the per-game loop.
    If unavailable, all games are batched to data_gather_failed, committed, and
    the function returns early (PM-783/Authority B §4.2).

    Success path (available=True):
      INSERT oracle_preliminary_data, INSERT oracle_lifecycle_audit,
      transition scheduled → preliminary_analysis,
      UPDATE oracle_game_analyses, record preliminary_data_gathered event.

    Failure path (available=False after all retries):
      INSERT oracle_lifecycle_audit, transition scheduled → data_gather_failed,
      UPDATE oracle_game_analyses, record data_gather_failed event.

    Caller owns the transaction (DCR-W5-001); conn.commit() called once at end.
    """
    _check_kill_switch(env=env)

    adapter = MLBAdapter()
    now = _now_utc()

    availability = adapter.get_availability()
    if not availability.available:
        for game_run_id in game_run_ids:
            game_id = game_run_id.rsplit("-", 1)[-1]
            _insert_lifecycle_audit(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                stage="3",
                event="data_gather_failed",
                detail=str(availability.reason) if availability.reason is not None else None,
            )
            transition_game_state("scheduled", "data_gather_failed")
            _update_game_status(conn, game_run_id, "data_gather_failed")
            record_event(
                conn, "data_gather_failed", slate_run_id, now,
                game_run_id=game_run_id,
            )
        conn.commit()
        return

    for game_run_id in game_run_ids:
        game_id = game_run_id.rsplit("-", 1)[-1]
        response = gather_preliminary_data(game_id, adapter)

        if response.availability.available and response.record is not None:
            record = response.record
            _insert_preliminary_data(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                data_version_id=record.data_version_id,
                game_id=game_id,
                gathered_at=record.gathered_at,
                raw_payload=json.dumps(record.raw_payload),
            )
            _insert_lifecycle_audit(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                stage="3",
                event="preliminary_data_gathered",
            )
            transition_game_state("scheduled", "preliminary_analysis")
            _update_game_status(conn, game_run_id, "preliminary_analysis")
            record_event(
                conn, "preliminary_data_gathered", slate_run_id, now,
                game_run_id=game_run_id,
            )
            logger.info(
                "Stage 3: game_run_id=%s data_version_id=%s",
                game_run_id, record.data_version_id,
            )
        else:
            reason = response.availability.reason
            _insert_lifecycle_audit(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                stage="3",
                event="data_gather_failed",
                detail=str(reason) if reason is not None else None,
            )
            transition_game_state("scheduled", "data_gather_failed")
            _update_game_status(conn, game_run_id, "data_gather_failed")
            record_event(
                conn, "data_gather_failed", slate_run_id, now,
                game_run_id=game_run_id,
            )
            logger.warning(
                "Stage 3: data gather failed for game_run_id=%s reason=%s",
                game_run_id, reason,
            )

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 4 — ECF Calculation (Structural ECF v1; authorized PM-867)
# ---------------------------------------------------------------------------

def run_stage_4(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 4 — ECF Calculation (Structural ECF v1; authorized PM-867).

    For each game with preliminary data (stage 3 success path):
      SELECT oracle_preliminary_data, compute ECF via stage4_ecf.compute_ecf(),
      INSERT oracle_ecf_results, INSERT oracle_lifecycle_audit (stage='4',
      event='ecf_calculated'), record ecf_calculated event.
      Game state remains in preliminary_analysis; Stage 5 transitions further.

    Games without preliminary data (data_gather_failed in Stage 3) are skipped.

    Failure path (ECF computation raises):
      INSERT oracle_lifecycle_audit (stage='4', event='preliminary_analysis_failed'),
      transition preliminary_analysis → preliminary_analysis_failed,
      UPDATE oracle_game_analyses, record preliminary_analysis_failed event.
      Dual-audit required: both oracle_play_events AND oracle_lifecycle_audit
      (P-4b binding — PM-859).

    Caller owns the transaction (DCR-W5-001); conn.commit() called once at end.
    """
    _check_kill_switch(env=env)

    now = _now_utc()

    for game_run_id in game_run_ids:
        row = _fetch_preliminary_record(conn, game_run_id)
        if row is None:
            continue

        raw_payload, data_version_id, gathered_at = row

        try:
            ecf_result = compute_ecf(
                game_run_id, data_version_id, raw_payload, gathered_at, now
            )
        except Exception as exc:
            _insert_lifecycle_audit(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                stage="4",
                event="preliminary_analysis_failed",
                detail=str(exc),
            )
            transition_game_state("preliminary_analysis", "preliminary_analysis_failed")
            _update_game_status(conn, game_run_id, "preliminary_analysis_failed")
            record_event(
                conn, "preliminary_analysis_failed", slate_run_id, now,
                game_run_id=game_run_id,
            )
            logger.warning(
                "Stage 4: ECF failed for game_run_id=%s: %s", game_run_id, exc
            )
            continue

        _insert_ecf_result(
            conn,
            ecf_result_id=ecf_result.ecf_result_id,
            game_run_id=game_run_id,
            data_version_id=data_version_id,
            ecf_score=ecf_result.ecf_score,
            component_scores={
                "data_completeness": ecf_result.components.data_completeness,
                "data_freshness": ecf_result.components.data_freshness,
                "data_payload_density": ecf_result.components.data_payload_density,
            },
            model_version=ecf_result.model_version,
            computed_at=now,
        )
        _insert_lifecycle_audit(
            conn,
            game_run_id=game_run_id,
            slate_run_id=slate_run_id,
            stage="4",
            event="ecf_calculated",
            detail=f"ecf_result_id={ecf_result.ecf_result_id} score={ecf_result.ecf_score:.4f}",
        )
        record_event(
            conn, "ecf_calculated", slate_run_id, now,
            game_run_id=game_run_id,
        )
        logger.info(
            "Stage 4: ecf_score=%.4f game_run_id=%s", ecf_result.ecf_score, game_run_id
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 5 — Multi-model Analysis Pipeline (Inc-3 MVP; authorized PM-1009/PM-1007)
# ---------------------------------------------------------------------------

class Stage5PolicyUnavailableError(OrchestratorError):
    """Raised when no active MLB sport policy is available at Stage 5."""


class Stage5CutoffConflictError(OrchestratorError):
    """Raised when an existing scheduled cutoff conflicts with the computed one."""


def _load_active_mlb_policy(conn: object):
    """Read and bind the active MLB sport policy at Stage 5 (D-4).

    Raises Stage5PolicyUnavailableError if no active MLB policy exists.
    """
    store = MLBSportPolicyStore(conn)
    response = store.get_active_policy("MLB")
    if response.outcome is not PolicyReadOutcome.RECORD_RETURNED or response.record is None:
        raise Stage5PolicyUnavailableError(
            f"active MLB sport policy unavailable: outcome={response.outcome}"
        )
    return response.record


def _fetch_latest_ecf_result(conn: object, game_run_id: str):
    """Return (ecf_result_id, data_version_id, ecf_score, component_scores) or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT ecf_result_id, data_version_id, ecf_score, component_scores
            FROM oracle_ecf_results
            WHERE game_run_id = %s
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_preliminary_payload(conn: object, game_run_id: str) -> dict:
    """Return the latest Stage 3 raw_payload dict for game_run_id, or {}."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT raw_payload
            FROM oracle_preliminary_data
            WHERE game_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if row is None or row[0] is None:
        return {}
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


def _fetch_first_pitch_time(conn: object, game_run_id: str):
    """Return the first_pitch_time for game_run_id, or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT first_pitch_time FROM oracle_game_analyses WHERE game_run_id = %s",
            (game_run_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return row[0] if row is not None else None


def _insert_stage5_result(conn: object, result) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_stage5_results
                (stage5_result_id, game_run_id, slate_run_id, ecf_result_id,
                 data_version_id, verdict, engine_outputs, model_version, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (result.stage5_result_id, result.game_run_id, result.slate_run_id,
             result.ecf_result_id, result.data_version_id, result.verdict,
             json.dumps(result.engine_outputs), result.model_version, result.computed_at),
        )
    finally:
        cur.close()


def _insert_preliminary_output(conn: object, result) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_preliminary_outputs
                (game_run_id, slate_run_id, stage5_result_id, consumer_status,
                 verdict, output_payload)
            VALUES (%s, %s, %s, 'Preliminary', %s, %s)
            """,
            (result.game_run_id, result.slate_run_id, result.stage5_result_id,
             result.verdict, json.dumps(result.preliminary_output_payload())),
        )
    finally:
        cur.close()


def _fetch_scheduled_cutoff(conn: object, game_run_id: str):
    """Return (slate_run_id, scheduled_cutoff_at, policy_version_id) or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT slate_run_id, scheduled_cutoff_at, policy_version_id
            FROM oracle_scheduled_cutoffs
            WHERE game_run_id = %s
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _insert_scheduled_cutoff(
    conn: object,
    game_run_id: str,
    slate_run_id: str,
    scheduled_cutoff_at: object,
    policy_version_id: str,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_scheduled_cutoffs
                (game_run_id, slate_run_id, scheduled_cutoff_at, policy_version_id)
            VALUES (%s, %s, %s, %s)
            """,
            (game_run_id, slate_run_id, scheduled_cutoff_at, policy_version_id),
        )
    finally:
        cur.close()


def _persist_scheduled_cutoff_with_replay(
    conn: object,
    game_run_id: str,
    slate_run_id: str,
    scheduled_cutoff_at: object,
    policy_version_id: str,
) -> None:
    """Insert the cutoff, or accept an equal existing row as idempotent replay.

    Replay semantics (PM-1007 §4): natural key is game_run_id; an existing row
    with identical slate, cutoff timestamp, and policy version is an idempotent
    replay (no duplicate). An existing row with any differing immutable value
    raises Stage5CutoffConflictError (deterministic conflict → rollback). A
    uniqueness violation alone is never treated as successful idempotency.
    """
    existing = _fetch_scheduled_cutoff(conn, game_run_id)
    if existing is None:
        _insert_scheduled_cutoff(
            conn, game_run_id, slate_run_id, scheduled_cutoff_at, policy_version_id
        )
        return
    existing_slate, existing_cutoff, existing_policy = existing
    if (
        existing_slate == slate_run_id
        and existing_cutoff == scheduled_cutoff_at
        and existing_policy == policy_version_id
    ):
        return  # idempotent replay — identical immutable values
    raise Stage5CutoffConflictError(
        f"scheduled cutoff conflict for {game_run_id}: existing "
        f"({existing_slate}, {existing_cutoff}, {existing_policy}) != computed "
        f"({slate_run_id}, {scheduled_cutoff_at}, {policy_version_id})"
    )


def run_stage_5(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 5 — Multi-model Analysis Pipeline (Inc-3 MVP; PM-1009 under PM-1007).

    Ratified R1 boundary. For each game with a Stage 4 ECF result:
      - consume the ECF result and its data-version identity;
      - run the four-engine MVP (GSE, MVE, ODG, SRL) via stage5_pipeline;
      - persist one immutable Stage 5 result and one immutable Preliminary
        consumer output;
      - durably persist the scheduled cutoff (first pitch + active MLB-A3-v1
        offset) with replay semantics;
      - write a lifecycle audit row to oracle_lifecycle_audit (D-5);
      - transition the game preliminary_analysis → lineup_monitoring;
      - emit multi_model_analysis_completed only after successful persistence.

    All effects commit atomically in one Orchestrator-owned transaction; any
    failure rolls the whole stage back with no partial result (DCR-W5-001).
    Stage 5 does NOT open the activation window (operative Stage 8) and never
    emits phie_completed or ce_completed (PHIE/CE deferred; PM-1007 D-2). Games
    without a Stage 4 ECF result are skipped.
    """
    _check_kill_switch(env=env)

    policy = _load_active_mlb_policy(conn)
    now = _now_utc()

    # Compute phase — reads only; engines are pure and deterministic.
    engine_inputs: list[GameEngineInput] = []
    for game_run_id in game_run_ids:
        ecf_row = _fetch_latest_ecf_result(conn, game_run_id)
        if ecf_row is None:
            continue
        ecf_result_id, data_version_id, ecf_score, component_scores = ecf_row
        if isinstance(component_scores, str):
            component_scores = json.loads(component_scores)
        first_pitch_time = _fetch_first_pitch_time(conn, game_run_id)
        if first_pitch_time is None:
            continue
        payload = _fetch_preliminary_payload(conn, game_run_id)
        engine_inputs.append(
            GameEngineInput(
                game_run_id=game_run_id,
                ecf_result_id=ecf_result_id,
                data_version_id=data_version_id,
                ecf_score=float(ecf_score),
                ecf_components=component_scores or {},
                ecf_model_version="",
                preliminary_payload=payload,
                first_pitch_time=first_pitch_time,
                market_moneyline=None,
            )
        )

    if not engine_inputs:
        logger.info("Stage 5: no games with Stage 4 results; nothing to process")
        conn.commit()
        return

    results = run_stage5_pipeline(slate_run_id, engine_inputs, now)
    first_pitch_by_game = {i.game_run_id: i.first_pitch_time for i in engine_inputs}

    # Persist phase — atomic across the slate; any failure rolls everything back.
    try:
        for game_run_id, result in results.items():
            _insert_stage5_result(conn, result)
            _insert_preliminary_output(conn, result)

            scheduled_cutoff_at = first_pitch_by_game[game_run_id] + policy.time_cutoff_offset
            _persist_scheduled_cutoff_with_replay(
                conn, game_run_id, slate_run_id, scheduled_cutoff_at,
                policy.policy_version_id,
            )

            _insert_lifecycle_audit(
                conn,
                game_run_id=game_run_id,
                slate_run_id=slate_run_id,
                stage="5",
                event="multi_model_analysis_completed",
                detail=(
                    f"stage5_result_id={result.stage5_result_id} "
                    f"verdict={result.verdict} policy={policy.policy_version_id}"
                ),
            )

            transition_game_state("preliminary_analysis", "lineup_monitoring")
            _update_game_status(conn, game_run_id, "lineup_monitoring")

            record_event(
                conn, "multi_model_analysis_completed", slate_run_id, now,
                game_run_id=game_run_id,
            )
            logger.info(
                "Stage 5: game_run_id=%s verdict=%s stage5_result_id=%s",
                game_run_id, result.verdict, result.stage5_result_id,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Stage 6 — Evidence-Safe Lineup Monitoring (Inc-3+ Option B; PM-1031/PM-1029)
# ---------------------------------------------------------------------------

class Stage6ReplayConflictError(OrchestratorError):
    """Raised when an existing observation shares a snapshot identity but has
    conflicting immutable stored values (data-integrity conflict → rollback)."""


def _fetch_lineup_observation_by_identity(conn: object, game_run_id: str, snapshot_identity: str):
    """Return stored canonical fields for an existing (game, snapshot) row, or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT home_lineup, away_lineup, home_starting_pitcher, away_starting_pitcher,
                   home_lineup_status, away_lineup_status
            FROM oracle_lineup_observations
            WHERE game_run_id = %s AND snapshot_identity = %s
            LIMIT 1
            """,
            (game_run_id, snapshot_identity),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_latest_lineup_observation(conn: object, game_run_id: str):
    """Return (snapshot_identity, home_lineup, away_lineup, home_sp, away_sp,
    home_status, away_status) for the latest canonical observation, or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT snapshot_identity, home_lineup, away_lineup, home_starting_pitcher,
                   away_starting_pitcher, home_lineup_status, away_lineup_status
            FROM oracle_lineup_observations
            WHERE game_run_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _insert_lineup_observation(
    conn: object, game_run_id: str, slate_run_id: str, snapshot_identity: str,
    observed_at: object, obs, policy_version_id: str, change_detected: bool,
    change_evidence: dict, prior_snapshot_identity: str | None,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_lineup_observations
                (game_run_id, slate_run_id, snapshot_identity, observed_at, source,
                 home_lineup, away_lineup, home_lineup_status, away_lineup_status,
                 home_starting_pitcher, away_starting_pitcher, policy_version_id,
                 change_detected, change_evidence, prior_snapshot_identity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (game_run_id, slate_run_id, snapshot_identity, observed_at, obs.source,
             json.dumps(list(obs.home_order)), json.dumps(list(obs.away_order)),
             obs.home_lineup_status, obs.away_lineup_status,
             json.dumps(obs.home_pitcher), json.dumps(obs.away_pitcher),
             policy_version_id, change_detected, json.dumps(change_evidence),
             prior_snapshot_identity),
        )
    finally:
        cur.close()


def run_stage_6(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> list[Stage6Result]:
    """Stage 6 — Evidence-Safe Lineup Monitoring (Option B; PM-1031/PM-1033 under PM-1029).

    Returns one explicit, immutable Stage6Result per game evaluated (PM-1033):
    the caller can distinguish UNAVAILABLE / PARTIAL / OBSERVED_FULL and the
    persisted / replay / change_detected facts without parsing logs, querying
    the database, or reading lifecycle-audit rows. This return contract is
    purely additive: it changes no classification, persistence rule, snapshot
    identity, event, or product meaning. On DB/transaction failure the whole
    stage rolls back and RAISES (no false success result is returned).

    One real, synchronous, idempotent lineup observation per game per invocation
    (no loop, timer, scheduler, worker, or retry). All MLB network access is in
    the adapter; this Core function only persists/decides. Per game:
      - obtain the adapter's evidence-safe LineupObservation;
      - UNAVAILABLE / PARTIAL → caller-visible outcome; lifecycle-audit note only;
        NO observation row, NO lineup event, NO state progress, NO recalculation;
      - OBSERVED_FULL → compute the deterministic snapshot identity;
          * identical replay (same identity, matching immutable values) → no
            duplicate row/event;
          * conflicting immutable replay → Stage6ReplayConflictError (rollback);
          * otherwise persist one immutable observation, emit
            lineup_observation_recorded, and emit lineup_change_detected iff the
            observed snapshot differs materially from the prior canonical one.

    Never emits lineup_confirmed or recalculation_triggered and never produces
    AUTHORITATIVELY_CONFIRMED (no authoritative provider semantics exist).
    Stage 6 remains in lineup_monitoring (no game_status change / transition);
    Stage 7 owns recalculation and the transition to final_analysis. One
    Orchestrator-owned transaction; any failure rolls the whole stage back.
    """
    _check_kill_switch(env=env)

    policy = _load_active_mlb_policy(conn)
    now = _now_utc()
    adapter = MLBAdapter()
    results: list[Stage6Result] = []

    try:
        for game_run_id in game_run_ids:
            game_id = game_run_id.rsplit("-", 1)[-1]
            obs = adapter.observe_lineup(game_id)

            if obs.classification != LINEUP_OBSERVED_FULL:
                # UNAVAILABLE or PARTIAL: audit-only; not a successful observation.
                _insert_lifecycle_audit(
                    conn, game_run_id=game_run_id, slate_run_id=slate_run_id,
                    stage="6", event="lineup_observation_unavailable",
                    detail=f"classification={obs.classification} status={obs.detail}",
                )
                results.append(Stage6Result(
                    game_run_id=game_run_id, classification=obs.classification,
                    persisted=False, replay=False, change_detected=False,
                    reason=(obs.detail or obs.classification),
                ))
                logger.info(
                    "Stage 6: game_run_id=%s classification=%s (no observation persisted)",
                    game_run_id, obs.classification,
                )
                continue

            snapshot_identity = compute_snapshot_identity(game_run_id, obs)
            current_canon = canonical_snapshot(obs)

            existing = _fetch_lineup_observation_by_identity(conn, game_run_id, snapshot_identity)
            if existing is not None:
                if canonical_from_stored(*existing) != current_canon:
                    raise Stage6ReplayConflictError(
                        f"conflicting immutable replay for {game_run_id} / {snapshot_identity}"
                    )
                results.append(Stage6Result(
                    game_run_id=game_run_id, classification=LINEUP_OBSERVED_FULL,
                    persisted=False, replay=True, change_detected=False,
                    snapshot_identity=snapshot_identity,
                ))
                logger.info(
                    "Stage 6: idempotent replay game_run_id=%s snapshot=%s",
                    game_run_id, snapshot_identity,
                )
                continue

            prior = _fetch_latest_lineup_observation(conn, game_run_id)
            prior_identity = prior[0] if prior else None
            prior_canon = canonical_from_stored(*prior[1:]) if prior else None
            change_detected, change_evidence = detect_material_change(current_canon, prior_canon)

            _insert_lineup_observation(
                conn, game_run_id, slate_run_id, snapshot_identity, now, obs,
                policy.policy_version_id, change_detected, change_evidence, prior_identity,
            )
            record_event(
                conn, "lineup_observation_recorded", slate_run_id, now,
                game_run_id=game_run_id,
            )
            if change_detected:
                record_event(
                    conn, "lineup_change_detected", slate_run_id, now,
                    game_run_id=game_run_id,
                )
            _insert_lifecycle_audit(
                conn, game_run_id=game_run_id, slate_run_id=slate_run_id,
                stage="6", event="lineup_observation_recorded",
                detail=f"snapshot={snapshot_identity} change_detected={change_detected}",
            )
            results.append(Stage6Result(
                game_run_id=game_run_id, classification=LINEUP_OBSERVED_FULL,
                persisted=True, replay=False, change_detected=change_detected,
                snapshot_identity=snapshot_identity,
            ))
            logger.info(
                "Stage 6: recorded game_run_id=%s snapshot=%s change_detected=%s",
                game_run_id, snapshot_identity, change_detected,
            )
        conn.commit()
        return results
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Stage 7 — Final Analysis (Option A finalization; PM-1047 / PM-1049 / PM-1051)
# ---------------------------------------------------------------------------

class Stage7FinalizationError(OrchestratorError):
    """Raised when a Stage 7 uniqueness conflict cannot be reconciled to a committed
    frozen record (data-integrity conflict → rollback)."""


_PG_UNIQUE_VIOLATION = "23505"


def _fetch_game_status(conn: object, game_run_id: str):
    """Return the actual persisted game_status for game_run_id, or None."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT game_status FROM oracle_game_analyses WHERE game_run_id = %s",
            (game_run_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return row[0] if row is not None else None


def _fetch_latest_stage5_result(conn: object, game_run_id: str):
    """Return (stage5_result_id, data_version_id, verdict) for the latest Stage 5 result,
    or None. The scalar verdict is copied verbatim; engine_outputs are never re-serialized
    (analytical values are bound by the immutable source identity)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT stage5_result_id, data_version_id, verdict
            FROM oracle_stage5_results
            WHERE game_run_id = %s
            ORDER BY computed_at DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_latest_canonical_observation(conn: object, game_run_id: str):
    """Return (snapshot_identity, observed_at) for the latest canonical OBSERVED_FULL
    observation, or None. Stage 7 binds persisted canonical observations only; it makes no
    claim about later non-persistent (UNAVAILABLE/PARTIAL) attempts it has not read."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT snapshot_identity, observed_at
            FROM oracle_lineup_observations
            WHERE game_run_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _fetch_stage7_final(conn: object, game_run_id: str):
    """Return the frozen final record's bound fields, or None:
    (bound_input_identity, stage5_result_id, data_version_id, policy_version_id,
     scheduled_cutoff_at, stage6_snapshot_identity, verdict)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT bound_input_identity, stage5_result_id, data_version_id,
                   policy_version_id, scheduled_cutoff_at, stage6_snapshot_identity, verdict
            FROM oracle_stage7_final_analysis
            WHERE game_run_id = %s
            """,
            (game_run_id,),
        )
        return cur.fetchone()
    finally:
        cur.close()


def _insert_stage7_final(
    conn: object, game_run_id: str, slate_run_id: str, stage5_result_id: str,
    data_version_id: str, policy_version_id: str, verdict: str,
    scheduled_cutoff_at: object, stage6_snapshot_identity: str, stage6_observed_at: object,
    cutoff_rel: str | None, bound_input_identity: str, limitations: list, assessment_at: object,
) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_stage7_final_analysis
                (game_run_id, slate_run_id, stage5_result_id, data_version_id,
                 policy_version_id, verdict, scheduled_cutoff_at, stage6_snapshot_identity,
                 stage6_observed_at, cutoff_relationship, bound_input_identity,
                 limitations, assessment_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (game_run_id, slate_run_id, stage5_result_id, data_version_id,
             policy_version_id, verdict, scheduled_cutoff_at, stage6_snapshot_identity,
             stage6_observed_at, cutoff_rel, bound_input_identity,
             json.dumps(limitations), assessment_at),
        )
    finally:
        cur.close()


def _has_stage7_divergence_audit(conn: object, game_run_id: str, bound_input_identity: str) -> bool:
    """True iff a divergence audit row already records this (game, current identity),
    enabling deduplicated divergence reporting."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT 1 FROM oracle_lifecycle_audit
            WHERE game_run_id = %s AND stage = '7'
              AND event = 'stage7_provenance_divergence'
              AND detail LIKE %s
            LIMIT 1
            """,
            (game_run_id, f"%{bound_input_identity}%"),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


def _acquire_divergence_lock(conn: object, game_run_id: str, bound_input_identity: str) -> None:
    """Serialize the divergence-audit check-then-insert across independent connections/
    transactions using a PostgreSQL transaction-scoped advisory lock, keyed on
    (game_run_id, current bound-input identity) and released automatically at commit/rollback.

    The lock is acquired BEFORE the deduplication SELECT; if a concurrent transaction holds it,
    this call waits until that transaction commits or rolls back. The caller then re-reads
    (_has_stage7_divergence_audit) under READ COMMITTED, so a row the other transaction committed
    is seen and the duplicate insert is skipped. This makes deduplication safe process-wide, not
    only within one Python process. It uses no shared audit-schema, state-machine, or unrelated
    writer changes.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
            (f"stage7_divergence:{game_run_id}:{bound_input_identity}",),
        )
        cur.fetchone()
    finally:
        cur.close()


def _reconcile_existing_final(conn, slate_run_id, game_run_id, frozen, stage5, cutoff, observation):
    """Classify a re-invocation against an existing frozen final record.

    Returns (Stage7FinalResult, wrote). The current bound-input identity is recomputed only
    from sufficiently-available valid inputs; missing comparison inputs yield
    UNAVAILABLE_INPUTS (never a false replay/divergence) and preserve the frozen record.
    A uniqueness violation is never equated with success. CHANGED_PROVENANCE appends exactly
    one deduplicated divergence audit row and never rewrites the frozen record.
    """
    (stored_identity, s_s5id, s_dv, s_policy, s_cutoff, s_snapshot, s_verdict) = frozen

    if stage5 is None or cutoff is None:
        return (
            s7.Stage7FinalResult(
                game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                reason=s7.REASON_UNREADABLE_COMPARISON_INPUTS,
                bound_input_identity=stored_identity, verdict=s_verdict,
                stage6_snapshot_identity=s_snapshot,
                limitations=s7.standing_limitations(),
            ),
            False,
        )

    # A missing or unusable current canonical observation must NOT be hashed as None (that
    # would falsely report CHANGED_PROVENANCE). Return UNAVAILABLE_INPUTS, preserve the frozen
    # record, and emit no divergence audit. (snapshot_identity is NOT NULL when a row exists.)
    if observation is None or observation[0] is None:
        return (
            s7.Stage7FinalResult(
                game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                reason=s7.REASON_NO_CANONICAL_OBSERVATION,
                bound_input_identity=stored_identity, verdict=s_verdict,
                stage6_snapshot_identity=s_snapshot,
                limitations=s7.standing_limitations(),
            ),
            False,
        )

    stage5_result_id, data_version_id, _verdict = stage5
    _cutoff_slate, scheduled_cutoff_at, policy_version_id = cutoff
    snapshot_identity = observation[0]

    current = s7.bound_inputs(
        stage5_result_id, data_version_id, policy_version_id,
        scheduled_cutoff_at, snapshot_identity,
    )
    current_identity = s7.compute_bound_input_identity(game_run_id, current)

    if current_identity == stored_identity:
        return (
            s7.Stage7FinalResult(
                game_run_id=game_run_id, outcome=s7.EXACT_REPLAY,
                bound_input_identity=stored_identity, stage5_result_id=s_s5id,
                verdict=s_verdict, stage6_snapshot_identity=s_snapshot,
                limitations=s7.standing_limitations(),
            ),
            False,
        )

    stored = s7.bound_inputs(s_s5id, s_dv, s_policy, s_cutoff, s_snapshot)
    differing = s7.differing_bound_inputs(current, stored)

    # Serialize the check-then-insert across independent connections, then re-read after any
    # wait (READ COMMITTED) before inserting, so exactly one matching audit row is written.
    _acquire_divergence_lock(conn, game_run_id, current_identity)
    wrote = False
    if not _has_stage7_divergence_audit(conn, game_run_id, current_identity):
        _insert_lifecycle_audit(
            conn, game_run_id=game_run_id, slate_run_id=slate_run_id,
            stage="7", event="stage7_provenance_divergence",
            detail=f"frozen_identity={stored_identity} current_identity={current_identity} "
                   f"differing={','.join(differing)}",
        )
        wrote = True
    return (
        s7.Stage7FinalResult(
            game_run_id=game_run_id, outcome=s7.CHANGED_PROVENANCE,
            bound_input_identity=stored_identity, stage5_result_id=s_s5id,
            verdict=s_verdict, stage6_snapshot_identity=s_snapshot,
            differing_inputs=differing, limitations=s7.standing_limitations(),
        ),
        wrote,
    )


def run_stage_7(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> list[s7.Stage7FinalResult]:
    """Stage 7 — Final Analysis (Option A; PM-1047 / PM-1049 / PM-1051).

    Finalizes the immutable Stage 5 scalar verdict with Stage 6 observation provenance: no
    lineup-adjusted calculation, no confidence increase; pitchers remain PROBABLE. "Final"
    does NOT establish official lineup confirmation, analytical freshness, or betting
    readiness. Emits NO event (immutable frozen record + lifecycle audit only; the event
    registry is unchanged).

    Per game, kill switch first, then the existing frozen final record is checked BEFORE
    first-finalization eligibility. If a frozen record exists, the bound-input identity is
    recomputed from currently-available valid inputs → EXACT_REPLAY (equal) or
    CHANGED_PROVENANCE (differs; one deduplicated divergence audit row); unreadable
    comparison inputs → UNAVAILABLE_INPUTS with the frozen record preserved. Otherwise
    first-finalization eligibility applies: actual game_status == 'lineup_monitoring'
    (else INELIGIBLE); Stage 5 result + scheduled cutoff readable and a canonical
    OBSERVED_FULL snapshot with a valid, non-future timezone-aware observed_at (else
    UNAVAILABLE_INPUTS). When eligible, one immutable final record is frozen, a lifecycle
    audit row written, and the game transitioned lineup_monitoring → final_analysis.

    One Orchestrator-owned transaction (DCR-W5-001): write outcomes commit once at the end
    and are returned only after commit; read-only invocations perform no commit. A
    uniqueness conflict on insert is recovered via ROLLBACK TO SAVEPOINT and reconciled by
    identity. Any failure rolls the whole stage back and raises.
    """
    _check_kill_switch(env=env)

    now = _now_utc()
    results: list[s7.Stage7FinalResult] = []
    wrote = False

    try:
        for game_run_id in game_run_ids:
            frozen = _fetch_stage7_final(conn, game_run_id)
            stage5 = _fetch_latest_stage5_result(conn, game_run_id)
            cutoff = _fetch_scheduled_cutoff(conn, game_run_id)
            observation = _fetch_latest_canonical_observation(conn, game_run_id)

            # Frozen-record precedence: replay/divergence never re-applies first-
            # finalization state/temporal eligibility (the game already advanced).
            if frozen is not None:
                result, did_write = _reconcile_existing_final(
                    conn, slate_run_id, game_run_id, frozen, stage5, cutoff, observation,
                )
                wrote = wrote or did_write
                results.append(result)
                continue

            status = _fetch_game_status(conn, game_run_id)
            if status != "lineup_monitoring":
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.INELIGIBLE,
                    reason=s7.REASON_NOT_IN_LINEUP_MONITORING,
                ))
                continue
            if stage5 is None:
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                    reason=s7.REASON_NO_STAGE5_RESULT,
                ))
                continue
            if cutoff is None:
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                    reason=s7.REASON_NO_SCHEDULED_CUTOFF,
                ))
                continue
            if observation is None:
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                    reason=s7.REASON_NO_CANONICAL_OBSERVATION,
                ))
                continue

            stage5_result_id, data_version_id, verdict = stage5
            _cutoff_slate, scheduled_cutoff_at, policy_version_id = cutoff
            snapshot_identity, observed_at = observation

            if not s7.is_timezone_aware(observed_at):
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                    reason=s7.REASON_INVALID_OBSERVATION_TIMESTAMP,
                ))
                continue
            if not s7.is_valid_non_future_observed_at(observed_at, now):
                results.append(s7.Stage7FinalResult(
                    game_run_id=game_run_id, outcome=s7.UNAVAILABLE_INPUTS,
                    reason=s7.REASON_FUTURE_OBSERVATION_TIMESTAMP,
                ))
                continue

            inputs = s7.bound_inputs(
                stage5_result_id, data_version_id, policy_version_id,
                scheduled_cutoff_at, snapshot_identity,
            )
            identity = s7.compute_bound_input_identity(game_run_id, inputs)
            cutoff_rel = s7.cutoff_relationship(observed_at, scheduled_cutoff_at)
            limitations = list(s7.standing_limitations())

            cur = conn.cursor()
            try:
                cur.execute("SAVEPOINT sp_stage7_final")
            finally:
                cur.close()
            try:
                _insert_stage7_final(
                    conn, game_run_id, slate_run_id, stage5_result_id, data_version_id,
                    policy_version_id, verdict, scheduled_cutoff_at, snapshot_identity,
                    observed_at, cutoff_rel, identity, limitations, now,
                )
            except Exception as exc:  # inspect SQLSTATE; re-raise anything but a uniqueness conflict
                if getattr(exc, "pgcode", None) != _PG_UNIQUE_VIOLATION:
                    raise
                cur = conn.cursor()
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_stage7_final")
                finally:
                    cur.close()
                frozen_now = _fetch_stage7_final(conn, game_run_id)
                if frozen_now is None:
                    raise Stage7FinalizationError(
                        f"uniqueness conflict for {game_run_id} with no committed frozen record"
                    )
                result, did_write = _reconcile_existing_final(
                    conn, slate_run_id, game_run_id, frozen_now, stage5, cutoff, observation,
                )
                wrote = wrote or did_write
                results.append(result)
                continue
            else:
                cur = conn.cursor()
                try:
                    cur.execute("RELEASE SAVEPOINT sp_stage7_final")
                finally:
                    cur.close()

            _insert_lifecycle_audit(
                conn, game_run_id=game_run_id, slate_run_id=slate_run_id,
                stage="7", event="stage7_final_analysis_recorded",
                detail=f"bound_input_identity={identity} stage5_result_id={stage5_result_id} "
                       f"cutoff_relationship={cutoff_rel}",
            )
            transition_game_state("lineup_monitoring", "final_analysis")
            _update_game_status(conn, game_run_id, "final_analysis")
            wrote = True
            results.append(s7.Stage7FinalResult(
                game_run_id=game_run_id, outcome=s7.FIRST_FINALIZATION,
                bound_input_identity=identity, stage5_result_id=stage5_result_id,
                verdict=verdict, stage6_snapshot_identity=snapshot_identity,
                cutoff_relationship=cutoff_rel, limitations=tuple(limitations),
            ))
            logger.info(
                "Stage 7: finalized game_run_id=%s stage5_result_id=%s identity=%s",
                game_run_id, stage5_result_id, identity,
            )

        if wrote:
            conn.commit()
        return results
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Stage 8 — Candidate Activation Window stub
# ---------------------------------------------------------------------------

def run_stage_8(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 8 stub — Candidate Activation Window (activation deferred to Phase 4).

    Kill switch enforced before the activation gate. Writes candidate_created
    per game as stub placeholder. Transitions each game: final_analysis →
    activation_eligible. Transitions slate: analysis_in_progress →
    activation_window_open.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 8 stub: candidate activation deferred to Phase 4")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "candidate_created", slate_run_id, now,
            game_run_id=game_run_id,
        )
        transition_game_state("final_analysis", "activation_eligible")
        _update_game_status(conn, game_run_id, "activation_eligible")

    transition_slate_state("analysis_in_progress", "activation_window_open")
    _update_slate_status(conn, slate_run_id, "activation_window_open")

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 9 — Pregame Lock stub
# ---------------------------------------------------------------------------

def run_stage_9(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 9 stub — Pregame Lock (lock logic deferred to Phase 4).

    Writes play_locked per game as stub placeholder.
    Transitions each game: activation_eligible → pregame_locked.
    Transitions slate: activation_window_open → pregame_locked.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 9 stub: pregame lock logic deferred to Phase 4")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "play_locked", slate_run_id, now,
            game_run_id=game_run_id,
        )
        transition_game_state("activation_eligible", "pregame_locked")
        _update_game_status(conn, game_run_id, "pregame_locked")

    transition_slate_state("activation_window_open", "pregame_locked")
    _update_slate_status(conn, slate_run_id, "pregame_locked")

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 10 — Settlement stub
# ---------------------------------------------------------------------------

def run_stage_10(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 10 stub — Settlement and CLV Calculation (deferred to Phase 5).

    Writes settlement_completed per game as stub placeholder.
    Transitions each game: pregame_locked → settled.
    Transitions slate: pregame_locked → settled.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 10 stub: settlement deferred to Phase 5")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "settlement_completed", slate_run_id, now,
            game_run_id=game_run_id,
        )
        transition_game_state("pregame_locked", "settled")
        _update_game_status(conn, game_run_id, "settled")

    transition_slate_state("pregame_locked", "settled")
    _update_slate_status(conn, slate_run_id, "settled")

    conn.commit()
    logger.info("Stage 10 complete: slate_run_id=%s settled", slate_run_id)


# ---------------------------------------------------------------------------
# Top-level Phase 1 run coordinator
# ---------------------------------------------------------------------------

def run_oracle_phase1(
    conn: object,
    current_date_et: date,
    env: dict | None = None,
) -> str:
    """Execute the full Phase 1 Oracle slate run (Stages 1–10).

    Each stage checks the kill switch before executing. Stage 1 is atomic
    (DCR-W5-001 §10). Stages 2–10 each commit independently. Exceptions
    from any stage propagate to the caller; the caller owns rollback for
    any in-progress stage transaction.

    Args:
        conn: psycopg2 connection with autocommit=False. Caller owns lifecycle.
        current_date_et: America/Toronto business date for this slate run.
        env: Optional env dict for kill switch injection (tests only).

    Returns:
        The Slate Run ID created by Stage 1.

    Raises:
        KillSwitchHaltError: If kill switch is inactive at any stage.
        Any other exception propagates from the failing stage.
    """
    slate_run_id = run_stage_1(conn, current_date_et, env=env)
    game_run_ids = run_stage_2(conn, slate_run_id, env=env)
    run_stage_3(conn, slate_run_id, game_run_ids, env=env)
    run_stage_4(conn, slate_run_id, game_run_ids, env=env)
    run_stage_5(conn, slate_run_id, game_run_ids, env=env)
    run_stage_6(conn, slate_run_id, game_run_ids, env=env)
    run_stage_7(conn, slate_run_id, game_run_ids, env=env)
    run_stage_8(conn, slate_run_id, game_run_ids, env=env)
    run_stage_9(conn, slate_run_id, game_run_ids, env=env)
    run_stage_10(conn, slate_run_id, game_run_ids, env=env)
    logger.info("Phase 1 run complete: slate_run_id=%s", slate_run_id)
    return slate_run_id
