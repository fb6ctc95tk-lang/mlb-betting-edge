"""Oracle Inc-3 — Concrete PostgreSQL-backed Sport Policy Store (A-3).

Implements the D-2 ``SportPolicyStore`` interface against the append-only
``oracle_sport_policies`` and ``oracle_sport_policy_active`` tables created by
migration 009. Provides Core with the PM-designated active policy record for a
sport at Stage 5 (D-4 ratified read location).

Connection and transaction ownership (DCR-W5-001): the caller (Orchestrator)
supplies a psycopg2 connection with ``autocommit=False`` and owns every
transaction. This store creates and closes cursors only; it never commits,
rolls back, or closes the connection.

Active-version designation (D-2 §4.4): the active version for a sport is the
most recently designated row in ``oracle_sport_policy_active`` (highest id).
Record creation and active designation are PM governance acts performed by
migration/seed or a later governed act; this store is read-only.
"""

from __future__ import annotations

from datetime import timedelta

from backend.oracle.sport_policy_store import (
    PolicyReadOutcome,
    PolicyReadResponse,
    SportPolicyRecord,
    SportPolicyStore,
)


class MLBSportPolicyStore(SportPolicyStore):
    """PostgreSQL-backed active-policy reader (D-2 §§4, 6; A-3 store)."""

    def __init__(self, conn: object) -> None:
        """Bind the store to a caller-owned psycopg2 connection.

        Args:
            conn: psycopg2 connection with autocommit=False. The caller owns
                the transaction lifecycle; this store only opens/closes cursors.
        """
        self._conn = conn

    def get_active_policy(self, sport_id: str) -> PolicyReadResponse:
        """Return the PM-designated active policy record for the sport (D-2 §6.1).

        Resolves the active ``policy_version_id`` from the latest
        ``oracle_sport_policy_active`` row for ``sport_id`` and returns the
        matching immutable ``oracle_sport_policies`` record.

        Outcome:
          RECORD_RETURNED — an active version exists and its policy row was read.
          NO_RECORD — the sport has no active designation or the designated
            version is missing.
          ERROR — the store read raised (Core applies retry logic).
        """
        try:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT policy_version_id
                    FROM oracle_sport_policy_active
                    WHERE sport_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (sport_id,),
                )
                active_row = cur.fetchone()
                if active_row is None:
                    return PolicyReadResponse(outcome=PolicyReadOutcome.NO_RECORD)

                active_version_id = active_row[0]

                cur.execute(
                    """
                    SELECT sport_id, policy_version_id, time_cutoff_offset_seconds,
                           finalization_event_types, qualifying_change_criteria,
                           governance_reference, created_at
                    FROM oracle_sport_policies
                    WHERE policy_version_id = %s
                    """,
                    (active_version_id,),
                )
                policy_row = cur.fetchone()
            finally:
                cur.close()
        except Exception:
            return PolicyReadResponse(outcome=PolicyReadOutcome.ERROR)

        if policy_row is None:
            return PolicyReadResponse(outcome=PolicyReadOutcome.NO_RECORD)

        (
            row_sport_id,
            policy_version_id,
            time_cutoff_offset_seconds,
            finalization_event_types,
            qualifying_change_criteria,
            governance_reference,
            created_at,
        ) = policy_row

        record = SportPolicyRecord(
            sport_id=row_sport_id,
            policy_version_id=policy_version_id,
            time_cutoff_offset=timedelta(seconds=int(time_cutoff_offset_seconds)),
            finalization_event_type_list=frozenset(finalization_event_types or ()),
            qualifying_change_criteria=qualifying_change_criteria,
            governance_record_reference=governance_reference,
            created_at=created_at,
        )
        return PolicyReadResponse(
            outcome=PolicyReadOutcome.RECORD_RETURNED,
            record=record,
        )
