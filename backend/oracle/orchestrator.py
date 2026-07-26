"""Oracle Phase 1 — Run Orchestrator (WP-4 T05–T08).

Coordinates the Phase 1 Oracle slate run lifecycle across Stages 1–10.
Stages 3–10 are Phase 1 stubs that write approved event types and transition
state machines; they do not call providers, engines, or LLMs.

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

import logging
from datetime import date, datetime, timezone

from backend.oracle.event_store import record_event
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
# Stage 3 — Preliminary Data Gather stub
# ---------------------------------------------------------------------------

def run_stage_3(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 3 stub — Preliminary Data Gather (providers deferred to Phase 2).

    game_analysis_started was already written by Stage 2; not repeated here
    (per P1-WP4-T07: 'writes game_analysis_started per game if not already
    written'). Transitions each game: scheduled → preliminary_analysis.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 3 stub: preliminary data gather deferred to Phase 2")

    for game_run_id in game_run_ids:
        transition_game_state("scheduled", "preliminary_analysis")
        _update_game_status(conn, game_run_id, "preliminary_analysis")

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 4 — ECF Calculation stub
# ---------------------------------------------------------------------------

def run_stage_4(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 4 stub — ECF Calculation (ECF engine deferred to Phase 3).

    Writes ecf_calculated per game. No game state transition.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 4 stub: ECF calculation deferred to Phase 3")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "ecf_calculated", slate_run_id, now,
            game_run_id=game_run_id,
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 5 — Intelligence Pipeline stub
# ---------------------------------------------------------------------------

_STAGE_5_PIPELINE_EVENTS: tuple[str, ...] = (
    "phie_completed",
    "gse_completed",
    "mve_completed",
    "ce_completed",
    "odg_completed",
    "srl_completed",
)


def run_stage_5(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 5 stub — Intelligence Pipeline (all engines deferred to Phase 3).

    Writes phie_completed, gse_completed, mve_completed, ce_completed,
    odg_completed, srl_completed per game, in that order.
    Transitions each game: preliminary_analysis → lineup_monitoring.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 5 stub: intelligence pipeline deferred to Phase 3")

    now = _now_utc()
    for game_run_id in game_run_ids:
        for event_type in _STAGE_5_PIPELINE_EVENTS:
            record_event(
                conn, event_type, slate_run_id, now,
                game_run_id=game_run_id,
            )
        transition_game_state("preliminary_analysis", "lineup_monitoring")
        _update_game_status(conn, game_run_id, "lineup_monitoring")

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 6 — Lineup Monitoring stub
# ---------------------------------------------------------------------------

def run_stage_6(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 6 stub — Lineup Monitoring (polling loop deferred to Phase 2).

    Writes lineup_observation_recorded per game. Games remain in
    lineup_monitoring state until Stage 7.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 6 stub: lineup monitoring/polling deferred to Phase 2")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "lineup_observation_recorded", slate_run_id, now,
            game_run_id=game_run_id,
        )

    conn.commit()


# ---------------------------------------------------------------------------
# Stage 7 — Final Analysis stub
# ---------------------------------------------------------------------------

def run_stage_7(
    conn: object,
    slate_run_id: str,
    game_run_ids: list[str],
    env: dict | None = None,
) -> None:
    """Stage 7 stub — Final Analysis and Recalculation (deferred to Phase 3).

    Writes recalculation_triggered per game as stub placeholder.
    Transitions each game: lineup_monitoring → final_analysis.
    """
    _check_kill_switch(env=env)
    logger.info("Stage 7 stub: final analysis/recalculation deferred to Phase 3")

    now = _now_utc()
    for game_run_id in game_run_ids:
        record_event(
            conn, "recalculation_triggered", slate_run_id, now,
            game_run_id=game_run_id,
        )
        transition_game_state("lineup_monitoring", "final_analysis")
        _update_game_status(conn, game_run_id, "final_analysis")

    conn.commit()


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
