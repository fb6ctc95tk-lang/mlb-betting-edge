"""Oracle — Sport Module Adapter interface contract (D-1 DESIGN ACCEPTED).

Defines the behavioral obligations the Oracle Core imposes on every Sport
Module adapter: MI-5 (availability), MI-1 (game-start timestamp), and the
Stage 6 observation call.  Data structures and abstract base class only;
no technology, protocol, or encoding is chosen (D-1 v1.1; PM-443).

Call direction (SI-3): Core initiates every call; adapters return values.
Engine-layer purity (CO-5, SI-4): CandidateChangeEvent.classification_fields
is opaque to Core and delivered to MI-3 exactly as received.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# MI-5 — Adapter availability (D-1 §6)
# ---------------------------------------------------------------------------

class UnavailabilityReason(enum.Enum):
    """Governed reason codes for adapter unavailability (D-1 §6.4)."""

    DATA_SOURCE_UNREACHABLE = "DATA_SOURCE_UNREACHABLE"
    ERROR_RESPONSE = "ERROR_RESPONSE"
    ADAPTER_INTERNAL_FAILURE = "ADAPTER_INTERNAL_FAILURE"


@dataclass(frozen=True)
class AvailabilityStatus:
    """MI-5 return value (D-1 §6.3).

    available=True: adapter can fulfil its obligations; reason must be None.
    available=False: adapter is unavailable; reason is required.

    Silent unavailability — returning Available when the adapter cannot serve,
    or returning no response — is prohibited (D-1 §6.4).
    """

    available: bool
    reason: UnavailabilityReason | None = None

    def __post_init__(self) -> None:
        if not self.available and self.reason is None:
            raise ValueError(
                "UnavailabilityReason is required when available is False"
            )
        if self.available and self.reason is not None:
            raise ValueError("reason must be None when available is True")


# ---------------------------------------------------------------------------
# MI-1 — Game-start timestamp (D-1 §3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimestampResponse:
    """MI-1 return value (D-1 §3.3).

    timestamp is None when availability.available is False.
    A missing timestamp must not be returned as a silent null (D-1 §3.5);
    the adapter must set available=False with an appropriate reason code.
    """

    timestamp: datetime | None
    availability: AvailabilityStatus


# ---------------------------------------------------------------------------
# Stage 6 observation call — response structures (D-1 §5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateChangeEvent:
    """One candidate change event from a Stage 6 observation call (D-1 §5.3).

    event_identity is the repeat-safety unit (D-1 §5.3 event identity
    invariant): the same underlying event occurrence must carry the same
    identity across multiple observation cycles.  Core uses event_identity
    for DP-4/Stage-7 duplicate suppression, not occurrence_timestamp.

    classification_fields carries the A-2-governed fields required by the
    DP-5 evaluator.  Core delivers these to MI-3 exactly as received
    without interpretation (CO-5, SI-4); no Core-layer parsing occurs.
    """

    event_identity: str
    occurrence_timestamp: datetime
    classification_fields: dict[str, Any] = field(default_factory=dict)


class FinalizationStatusCode(enum.Enum):
    """Finalization portion status codes for a Stage 6 observation response (D-1 §5.2)."""

    EVENT_PRESENT = "EVENT_PRESENT"
    NO_EVENT = "NO_EVENT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class FinalizationEventRecord:
    """Finalization event record included when a game-complete condition is detected (D-1 §5.4).

    event_type_identifier is validated by Core against the A-3-designated
    type in the MI-2 sport policy before the revision window is closed.
    """

    event_type_identifier: str
    event_timestamp: datetime


@dataclass(frozen=True)
class FinalizationStatus:
    """Finalization portion of a Stage 6 observation call response (D-1 §5.2).

    EVENT_PRESENT: game-complete condition detected; record is required.
    NO_EVENT: no finalization event detected this cycle.
    UNAVAILABLE: adapter cannot report finalization status this cycle.
    """

    code: FinalizationStatusCode
    record: FinalizationEventRecord | None = None

    def __post_init__(self) -> None:
        if self.code is FinalizationStatusCode.EVENT_PRESENT and self.record is None:
            raise ValueError(
                "FinalizationEventRecord is required when code is EVENT_PRESENT"
            )
        if (
            self.code is not FinalizationStatusCode.EVENT_PRESENT
            and self.record is not None
        ):
            raise ValueError("record must be None when code is not EVENT_PRESENT")


@dataclass(frozen=True)
class ObservationResponse:
    """Complete return value of a Stage 6 observation call (D-1 §5.2).

    When availability.available is False: candidate_events must be empty
    and finalization_status.code must be UNAVAILABLE (D-1 §5.5).
    An empty candidate_events tuple with code=NO_EVENT and available=True
    is valid: no changes were detected since the previous call.
    """

    candidate_events: tuple[CandidateChangeEvent, ...]
    finalization_status: FinalizationStatus
    availability: AvailabilityStatus


# ---------------------------------------------------------------------------
# Abstract adapter base class (D-1 §§3, 5, 6, 9)
# ---------------------------------------------------------------------------

class SportModuleAdapter(ABC):
    """Abstract base class for Oracle Sport Module adapters (D-1 §9).

    A concrete subclass (e.g. MLBSportModuleAdapter) implements these three
    methods for a specific sport.  Core depends only on this interface;
    adapter internals are not visible to Core (SI-2).

    All calls are Core-initiated (SI-3).  Concrete adapters must never:
      - Initiate contact with Core
      - Write directly to any Oracle table or issue commit or rollback on Oracle
        database connections (CO-2, DCR-W5-001); oracle_play_events and
        oracle_immutability_audit are included examples — all Oracle state
        changes and transaction boundaries are Orchestrator-owned
    """

    @abstractmethod
    def get_availability(self) -> AvailabilityStatus:
        """MI-5: return the adapter's current availability status (D-1 §6).

        Called by Core before Stage 2 (mandatory) and at any stage gate.
        Every unavailability condition must be declared explicitly with a
        reason code; silent failure is prohibited (D-1 §6.4).
        """

    @abstractmethod
    def get_game_start_timestamp(self, game_id: str) -> TimestampResponse:
        """MI-1: return the game-start timestamp for the identified game (D-1 §3).

        Called by Core during Stage 2 game activation.  If the timestamp
        cannot be provided the adapter must return available=False; a missing
        value must not be returned as a silent null (D-1 §3.5).
        """

    @abstractmethod
    def observe(self, game_id: str) -> ObservationResponse:
        """Stage 6 observation call (D-1 §5).

        Called by Core at each Stage 6 observation cycle, after Core has
        confirmed the kill switch is active (CO-1).  Returns candidate
        change events, finalization status, and availability in one response.

        When unavailable: candidate_events must be empty and
        finalization_status.code must be UNAVAILABLE.  Adapter recovery
        in a subsequent cycle is transparent; no acknowledgment required
        (D-1 §5.5, §6.5).
        """
