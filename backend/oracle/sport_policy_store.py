"""Oracle — Sport Policy Store interface contract (D-2 DESIGN ACCEPTED).

Defines the policy record structure and the read interface the Oracle Core
uses at Stage 2 to retrieve the PM-designated active policy record for a
sport. Storage technology, serialization format, versioning mechanism, and
PM governance write path are Phase C implementation decisions (D-2 §12;
PM-491).

Active-version designation (D-2 §4.4): record creation and active-version
designation are separate PM governance acts; creation or version ordering
alone does not confer active status. The store maintains a governed
per-sport active-version pointer updated only by PM governance acts.

Call direction (D-2 §6.1): Core initiates every read; the store returns a
consistent snapshot. Core has no write access to the store (D-2 §6.4).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Policy record (D-2 §3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SportPolicyRecord:
    """A single PM-governed sport policy record (D-2 §3.1).

    Immutable after creation (D-2 §4.1): field values cannot change after
    creation; a policy update produces a new record with a new
    policy_version_id; the prior record is preserved in the store.

    qualifying_change_criteria is opaque to Core (CO-5; D-2 §3.2): Core
    passes it to the MI-3 evaluator at Stage 6 without interpretation.

    time_cutoff_offset is added by the Orchestrator to the MI-1 game-start
    timestamp at Stage 5 to compute the scheduled window-close time
    (D-2 §3.4). timedelta is the sport-neutral Python duration type; the
    governing unit and storage encoding are Phase C decisions.

    finalization_event_type_list supports set membership queries at Stage 6
    (D-2 §3.3); frozenset preserves immutability of the record as a whole.
    The list encoding is a Phase C decision.
    """

    sport_id: str
    policy_version_id: str
    time_cutoff_offset: timedelta
    finalization_event_type_list: frozenset[str]
    qualifying_change_criteria: Any
    governance_record_reference: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Read interface response (D-2 §6.2)
# ---------------------------------------------------------------------------

class PolicyReadOutcome(enum.Enum):
    """Outcome codes for the policy store read interface (D-2 §6.2)."""

    RECORD_RETURNED = "RECORD_RETURNED"
    NO_RECORD = "NO_RECORD"
    ERROR = "ERROR"


@dataclass(frozen=True)
class PolicyReadResponse:
    """Return value of the policy store read interface (D-2 §6.1, §6.2).

    RECORD_RETURNED: record is the PM-designated active policy record; Core
      records policy_version_id, retains policy values in run context, and
      Stage 2 proceeds (D-2 §5.1, §6.2).
    NO_RECORD: no policy record found for the sport identifier, or no
      active version has been PM-designated; Stage 2 cannot proceed;
      Core enters failure state (D-2 §5.4, §6.2).
    ERROR: store unreachable or returns an error; Core applies retry logic;
      on exhaustion, enters failure state (D-2 §5.4, §6.2).

    record is None when outcome is not RECORD_RETURNED (D-2 §6.2).
    """

    outcome: PolicyReadOutcome
    record: SportPolicyRecord | None = None

    def __post_init__(self) -> None:
        if self.outcome is PolicyReadOutcome.RECORD_RETURNED and self.record is None:
            raise ValueError(
                "SportPolicyRecord is required when outcome is RECORD_RETURNED"
            )
        if (
            self.outcome is not PolicyReadOutcome.RECORD_RETURNED
            and self.record is not None
        ):
            raise ValueError("record must be None when outcome is not RECORD_RETURNED")


# ---------------------------------------------------------------------------
# Abstract store (D-2 §§4, 6)
# ---------------------------------------------------------------------------

class SportPolicyStore(ABC):
    """Abstract base class for the Oracle sport policy store (D-2 §§4, 6).

    A concrete subclass implements this interface for a specific storage
    technology (a Phase C decision). Core depends only on this interface;
    storage and governance-write internals are not visible to Core.

    All concrete stores must enforce (D-2 §§4.1, 4.2, 4.4, 6.4):
      - Append-only immutability: policy record field values cannot change
        after creation; updates produce new records with new policy_version_id
      - PM-governed write path: record creation and active-version designation
        are restricted to the PM governance channel; Core and runtime pipeline
        processes must not have write access to policy records
      - Explicit active-version designation: the PM-designated active version
        is tracked by a governed per-sport pointer updated only by PM
        governance acts; version ordering alone does not confer active status
    """

    @abstractmethod
    def get_active_policy(self, sport_id: str) -> PolicyReadResponse:
        """Return the PM-designated active policy record for the sport (D-2 §6.1).

        Called by Core at Stage 2 game activation; not called at subsequent
        stages during an active run (D-2 §6.1). Returns a consistent snapshot
        of a single policy record; partial or torn reads are not permitted
        (D-2 §6.1).

        Outcome (D-2 §6.2):
          RECORD_RETURNED — PM-designated active version exists for sport_id;
            record carries all fields including policy_version_id for Stage 2
            run binding (D-2 §5.1).
          NO_RECORD — sport not registered or no active version designated;
            Stage 2 enters failure state (D-2 §5.4).
          ERROR — store unreachable or returns error; Core applies retry
            logic; on exhaustion, Stage 2 enters failure state (D-2 §5.4).
        """
