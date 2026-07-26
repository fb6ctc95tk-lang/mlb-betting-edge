"""Oracle Phase 1 — Event Store Service.

Provides the sole application-layer write path to oracle_play_events.
Implements the caller-owned connection and transaction model per DCR-W5-001.
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.oracle.identifier_manager import (
    _require_manual_transaction,
    is_valid_slate_run_id,
)


# ---------------------------------------------------------------------------
# Event type registry — 28 approved types (DCR-W5-001 §15; enumeration is
# authoritative despite planning text labelling the list as "27")
# ---------------------------------------------------------------------------

_EVENT_TYPES: frozenset[str] = frozenset({
    "slate_initialized",
    "schedule_retrieved",
    "game_analysis_started",
    "ecf_calculated",
    "phie_completed",
    "gse_completed",
    "mve_completed",
    "ce_completed",
    "odg_completed",
    "srl_completed",
    "candidate_created",
    "candidate_reentered",
    "evaluation_version_created",
    "recalculation_triggered",
    "lineup_observation_recorded",
    "lineup_confirmed",
    "lineup_change_detected",
    "play_id_assigned",
    "play_activated",
    "play_locked",
    "conditional_play_nominated",
    "conditional_resolved",
    "conditional_expired",
    "settlement_completed",
    "settlement_manual_required",
    "le_milestone_detected",
    "le_report_stored",
    "immutability_violation_rejected",
})


def record_event(
    conn: object,
    event_type: str,
    slate_run_id: str,
    event_timestamp: datetime,
    game_run_id: str | None = None,
    play_id: str | None = None,
    payload: dict | None = None,
) -> int:
    """Insert one event into oracle_play_events and return the database-assigned event_id.

    Connection and transaction ownership: caller (DCR-W5-001).
    conn must have autocommit disabled. This function creates and closes
    one cursor. It does not commit, roll back, or close the connection.

    Validation order:
        1. event_type validated against the 28-type registry (before cursor open).
        2. slate_run_id validated against the Slate Run ID format (before cursor open).
        3. Cursor opened; INSERT executed; cursor closed.

    Args:
        conn: Caller-supplied psycopg2 connection with autocommit=False.
        event_type: One of the 28 approved Oracle event types.
        slate_run_id: A valid Slate Run ID (ORACLE-YYYYMMDD-NNN).
        event_timestamp: UTC timestamp for this event.
        game_run_id: Optional Game Analysis Run ID; None for slate-level events.
        play_id: Optional Play ID; None for events without a play context.
        payload: Optional JSONB payload dict; None if not applicable.

    Returns:
        The BIGSERIAL event_id assigned by the database.

    Raises:
        ValueError: If event_type is not in the approved registry (before cursor open).
        ValueError: If slate_run_id is not a valid Slate Run ID (before cursor open).
        InvalidConnectionStateError: If conn has autocommit enabled.
        Any psycopg2 exception propagates unchanged.
    """
    if event_type not in _EVENT_TYPES:
        raise ValueError(
            f"Unknown event type {event_type!r}. "
            f"Must be one of the {len(_EVENT_TYPES)} approved Oracle event types."
        )
    if not is_valid_slate_run_id(slate_run_id):
        raise ValueError(
            f"Invalid slate_run_id {slate_run_id!r}. "
            "Expected format: ORACLE-YYYYMMDD-NNN."
        )
    _require_manual_transaction(conn)

    payload_value = json.dumps(payload) if payload is not None else None

    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO oracle_play_events
                (event_type, slate_run_id, game_run_id, play_id,
                 event_timestamp, event_payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING event_id
            """,
            (event_type, slate_run_id, game_run_id, play_id,
             event_timestamp, payload_value),
        )
        event_id: int = cur.fetchone()[0]
    finally:
        cur.close()

    return event_id
