"""Oracle — Consumer/Administrator Interface contract (D-3 DESIGN ACCEPTED, v1.4).

Defines the role model, alert structures, Core pipeline signal structures,
administrator action request/response structures, pipeline-status result
contract, audit query structure, and the abstract interface contract through
which authorized principals observe pipeline state and submit bounded
administrator action requests.

UI framework, notification protocol, authentication mechanism, role-assignment
storage, kill-switch register technology, and audit query API are Phase C
implementation decisions (D-3 §11; PM-496).

Core supplies all eligibility and window state (D-3 §8.1): AE-C3.5
eligibility, Case B state, T−60 boundary, and cancellation window state are
Core-supplied signals. The interface observes and presents them; it does not
independently compute or approximate any of these values.

Audit row structure is D-4's scope (D-3 §5.4): this module creates no D-4
row type definitions and no E-item frozenset event identities.

PipelineStatusResult field composition, filtering, recency window, transport,
serialization, and UI are Phase C decisions (D-3 §§2.2, 11).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Role and severity enumerations (D-3 §§2.1, 3.1)
# ---------------------------------------------------------------------------

class Role(enum.Enum):
    """Principal role for interface access control (D-3 §2.1).

    CONSUMER: read-only observational access; no state-changing actions.
    ADMINISTRATOR: all consumer capabilities plus bounded enumerated actions;
      every state-changing action is audited and requires confirmation.

    Role enforcement is the access-control layer's responsibility (D-3 §2.4);
    this enum expresses the governed role vocabulary, not the enforcement.
    """

    CONSUMER = "CONSUMER"
    ADMINISTRATOR = "ADMINISTRATOR"


class AlertSeverity(enum.Enum):
    """Alert severity levels recognised by the interface (D-3 §3.1).

    STANDARD: governed operational conditions requiring awareness; no
      immediate intervention required; both surfaces observe.
    CRITICAL: governed conditions requiring immediate attention; may trigger
      automatic pipeline behaviors (e.g., C-3 Case A fallback); must be
      visually and structurally distinct from STANDARD; must not auto-dismiss;
      requires sport context (D-3 §3.3; PM-510 C-1).
    """

    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class KillSwitchState(enum.Enum):
    """Kill-switch state for ORACLE_AUTONOMOUS_RUN_ENABLED (D-3 §4.3; CO-1).

    ACTIVE: autonomous runs are enabled; Core kill-switch check passes.
    INACTIVE: autonomous runs are disabled; Core kill-switch check halts.

    Kill-switch state changes through the interface require administrator role,
    explicit confirmation, and generate governed audit rows (D-3 §4.3).
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# Administrator action vocabulary (D-3 §§4.1–4.3, §6.1)
# ---------------------------------------------------------------------------

class AdminActionType(enum.Enum):
    """Bounded set of administrator pipeline actions available through the interface (D-3 §6.1).

    This enumeration is exhaustive for pipeline actions. No pipeline action
    outside this set may be made available without a PM-directed D-3 successor
    (D-3 §6.2). Critical-alert acknowledgment is a separately governed
    administrator capability, not a pipeline action (D-3 §§4.4, 6.2).

    CANCELLATION: execute C-3 Case A fallback cancellation within the
      Core-signaled 5-minute window (D-3 §4.1; C-3 AE-C3.6).
    MANUAL_STAGE_1_INITIATION: initiate Stage 1 manually when the Case A
      fallback mechanism itself has failed (D-3 §4.2; C-3 AE-C3.5); not
      available at or after Core-reported T−60; not available during Case B.
      The T−60 boundary governs the initiation window only — successful
      recovery means Core execution begun before T−60; Stage 1 execution
      itself may extend past T−60 (D-3 §4.2; PM-501-D; PM-510 C-5).
    KILL_SWITCH_SET: set kill switch to ACTIVE (enable autonomous run)
      (D-3 §4.3; CO-1).
    KILL_SWITCH_CLEAR: set kill switch to INACTIVE (disable autonomous run)
      (D-3 §4.3; CO-1).
    """

    CANCELLATION = "CANCELLATION"
    MANUAL_STAGE_1_INITIATION = "MANUAL_STAGE_1_INITIATION"
    KILL_SWITCH_SET = "KILL_SWITCH_SET"
    KILL_SWITCH_CLEAR = "KILL_SWITCH_CLEAR"


class AdminActionOutcome(enum.Enum):
    """Outcome of a submitted administrator action request (D-3 §§4.1–4.3, §7.2)."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Alert structure (D-3 §§3.2–3.3; PM-510 C-1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    """A single alert delivered through the interface (D-3 §§3.2–3.3).

    severity must be presented explicitly and unambiguously; CRITICAL alerts
    must be visually and structurally distinct from STANDARD alerts (D-3 §3.1).

    audit_row_reference provides traceability to the governing
    oracle_immutability_audit row (D-3 §3.2); row type definition is D-4 scope.

    sport carries the sport context required for CRITICAL alerts (D-3 §3.3;
    PM-510 C-1). Must be non-None when severity is CRITICAL; enforced by
    __post_init__. May be None for STANDARD alerts.

    game_run_id must be non-None for CRITICAL alerts (D-3 §3.3; PM-513 C-1);
    may be None for STANDARD alerts.

    alert_reference is the opaque str identifier used to target this alert for
    acknowledgment via acknowledge_critical_alert (D-3 §4.4; PM-503-B;
    PM-513 C-2). Must be non-None for CRITICAL alerts; enforced by
    __post_init__. May be None for STANDARD alerts. alert_reference is
    distinct from audit_row_reference — no equivalence is assumed; they serve
    different purposes (acknowledgment targeting vs. audit traceability).

    CRITICAL alerts must not auto-dismiss; they persist until explicitly
    acknowledged via acknowledge_critical_alert by an authorized administrator
    (D-3 §3.3; PM-510 C-4).
    """

    severity: AlertSeverity
    event_timestamp: datetime
    description: str
    audit_row_reference: str
    game_run_id: str | None = None
    sport: str | None = None
    alert_reference: str | None = None
    acknowledged: bool = False

    def __post_init__(self) -> None:
        if self.severity is AlertSeverity.CRITICAL:
            if self.game_run_id is None:
                raise ValueError(
                    "Critical alerts require game run identifier (D-3 §3.3; PM-513 C-1)"
                )
            if self.sport is None:
                raise ValueError(
                    "Critical alerts require sport context (D-3 §3.3; PM-510 C-1)"
                )
            if self.alert_reference is None:
                raise ValueError(
                    "Critical alerts require alert_reference for acknowledgment "
                    "targeting (D-3 §4.4; PM-513 C-2)"
                )


# ---------------------------------------------------------------------------
# Core-supplied pipeline signals (D-3 §§3.4, 4.1, 4.2, 4.3, 8.1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CancellationWindowState:
    """Core-supplied cancellation window state (D-3 §§3.4, 4.1; C-3 AE-C3.6).

    anchor_timestamp: the UTC moment at which the Core initiated Stage 1 via
      the Case-A immediate fallback path; all window timing is measured from
      this Core-supplied anchor (D-3 §§3.4, 4.1).
    close_timestamp: anchor_timestamp plus 5 minutes as reported by the Core
      (D-3 §3.4); the interface presents this value; it does not compute it
      from a local clock.
    is_open: Core-supplied window open/close state; cancellation is available
      only when is_open is True (D-3 §4.1). Window open/close determination
      is a Core act; the interface enforces Core-supplied state.
    """

    anchor_timestamp: datetime
    close_timestamp: datetime
    is_open: bool


@dataclass(frozen=True)
class CorePipelineSignals:
    """All Core-supplied state signals consumed by the interface (D-3 §8.1).

    The interface observes these signals and presents surfaces and availability
    accordingly. It does not independently compute or approximate any of these
    values from local clocks, alert receipt times, or internal heuristics
    (D-3 §8.1).

    ae_c3_5_eligible: Core signals that the Case A fallback mechanism has
      failed and manual Stage 1 initiation is eligible (D-3 §4.2; C-3 AE-C3.5).
      Becomes False once Core has begun Stage 1 execution — whether the
      administrator submitted and Core accepted and begun executing the request,
      or Core initiated Stage 1 independently. The T−60 boundary governs
      the initiation window; this signal governs surface availability
      (D-3 §4.2; PM-501-D; PM-510 C-5).
    case_b_active: Core signals that the pipeline is in Case B; the manual
      Stage 1 initiation surface is disabled throughout Case B (D-3 §4.2).
    t_minus_60_reached: Core signals that the T−60 boundary has been reached
      or passed; the manual Stage 1 initiation surface is disabled (D-3 §4.2).
      The T−60 boundary governs the initiation window only — successful
      recovery means Core execution begun before T−60; Stage 1 execution
      itself may extend past T−60 (D-3 §4.2; PM-501-D; PM-510 C-5).
    kill_switch_active: current CO-1 kill-switch state as supplied by Core
      (D-3 §4.3); True means ORACLE_AUTONOMOUS_RUN_ENABLED is active.
    cancellation_window: Core-supplied cancellation window state; None when
      no Case A fallback window is active (D-3 §§3.4, 4.1).
    """

    ae_c3_5_eligible: bool
    case_b_active: bool
    t_minus_60_reached: bool
    kill_switch_active: bool
    cancellation_window: CancellationWindowState | None = None


# ---------------------------------------------------------------------------
# Administrator action request and response (D-3 §§4.1–4.3, §6.2, §7.2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdminActionRequest:
    """A confirmed administrator pipeline action request (D-3 §§4.1–4.3, §6.2).

    action_type identifies the bounded administrator pipeline action being
      submitted (one of the four actions in AdminActionType).
    administrator_identity carries the authenticated principal's identity for
      inclusion in the audit record (D-3 §§4.1–4.3).
    confirmation_recorded must be True; the interface enforces confirmation
      before submission for every state-changing administrator action (D-3 §6.2).
    game_run_id is required for CANCELLATION and MANUAL_STAGE_1_INITIATION;
      not applicable for kill-switch actions (D-3 §§4.1–4.2).

    Critical-alert acknowledgment is a separately governed capability submitted
    via acknowledge_critical_alert, not via this request type (D-3 §§4.4, 6.2).
    """

    action_type: AdminActionType
    administrator_identity: str
    confirmation_recorded: bool
    game_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.confirmation_recorded:
            raise ValueError(
                "confirmation_recorded must be True; confirmation is mandatory "
                "for all administrator actions (D-3 §6.2)"
            )


@dataclass(frozen=True)
class AdminActionResponse:
    """Result of a submitted administrator pipeline action request (D-3 §§4.1–4.3, §7.2).

    ACCEPTED: the Core has accepted and begun executing the action; audit row
      will be written by the Core (D-3 §5.3). For MANUAL_STAGE_1_INITIATION,
      ACCEPTED confirms Core execution begun before Core-reported T−60; an
      implementation must not return ACCEPTED for this action until Core
      confirms execution has begun — queued acceptance (Core accepted but
      deferred execution) is insufficient (D-3 §4.2; PM-501-D; PM-513 C-3).
    REJECTED: the Core rejected the action (e.g., cancellation submitted when
      Core-supplied window state indicates closed; manual Stage 1 submitted
      after T−60 boundary or during Case B); rejection is also audited
      (D-3 §7.2). rejection_reason describes the rejection.

    rejection_reason is required when outcome is REJECTED; must be None
    when outcome is ACCEPTED (D-3 §7.2).
    """

    outcome: AdminActionOutcome
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is AdminActionOutcome.REJECTED and self.rejection_reason is None:
            raise ValueError(
                "rejection_reason is required when outcome is REJECTED (D-3 §7.2)"
            )
        if (
            self.outcome is AdminActionOutcome.ACCEPTED
            and self.rejection_reason is not None
        ):
            raise ValueError(
                "rejection_reason must be None when outcome is ACCEPTED"
            )


# ---------------------------------------------------------------------------
# Audit row query (D-3 §5.1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditRowQuery:
    """Query parameters for the oracle_immutability_audit read interface (D-3 §5.1).

    All parameters are optional; at least one should be supplied for a
    meaningful query. Specific query execution and additional parameters
    are Phase C implementation decisions (D-3 §5.1).

    These are the minimum query dimensions required by D-3 §5.1:
      game_run_id, date range (date_from / date_to), event_type,
      and admin_action_type.
    """

    game_run_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    event_type: str | None = None
    admin_action_type: AdminActionType | None = None


# ---------------------------------------------------------------------------
# Pipeline status result contract (D-3 §2.2; PM-503-A; PM-510 C-2)
# ---------------------------------------------------------------------------

class PipelineStatusResult(ABC):
    """Opaque, read-only pipeline-status result type (D-3 §2.2; PM-503-A).

    Field composition (field names and field types), filtering behavior,
    recency window, transport encoding, serialization format, and UI
    presentation are Phase C implementation decisions (D-3 §§2.2, 11).

    The P-3b contract commits to this type name and its read-only character.
    Implementations must subclass PipelineStatusResult and add Phase C fields;
    the subclass must be immutable (e.g., a frozen dataclass or equivalent
    read-only construct). Accessible to both consumer and administrator roles
    (D-3 §§2.2, 6.1).
    """


# ---------------------------------------------------------------------------
# Abstract interface (D-3 §§2.1, 3, 4, 5, 8)
# ---------------------------------------------------------------------------

class ConsumerAdminInterface(ABC):
    """Abstract base class for the Oracle consumer/administrator interface (D-3, v1.4).

    A concrete subclass implements this interface for a specific technology
    surface (a Phase C decision). All principals interact with the pipeline
    through this contract; the Core and storage internals are not visible.

    All concrete implementations must observe (D-3 §§8.1, 8.2, 8.3, 8.4):
      - Core supplies all state: AE-C3.5 eligibility, Case B state, T−60
        boundary, and cancellation window state are Core-supplied signals;
        the implementation must not independently compute or approximate
        these values from local clocks or internal heuristics (D-3 §8.1)
      - No write to oracle_play_events: CO-4 — all oracle_play_events writes
        are Core acts; the interface has no write path to that table
      - No audit row writes: audit rows (including acknowledgment audit rows)
        are written by the Core as part of processing confirmed administrator
        action requests and acknowledgments (D-3 §§5.3, 4.4; CO-4)
      - C-10/C-11 — Core acts only; no surface, prompt, or control for any
        principal may influence, override, or pre-empt a determination
        (D-3 §§8.2–8.3); confirmed post-determination C-10 (Edge/No Edge)
        and C-11 (Formal No Play) outcomes may be included as read-only fields
        in the PipelineStatusResult returned by get_pipeline_status (D-3 §8.2;
        PM-510 C-5)
      - No PM governance surfaces: PM governance acts are not available
        through the interface (D-3 §8.4)
      - Confirmation enforced at surface level: confirmation_recorded must be
        True before AdminActionRequest is submitted (D-3 §6.2); this is
        validated by AdminActionRequest.__post_init__ and must also be
        enforced by the concrete implementation's action submission surface
      - Role enforcement: the access-control layer must prevent consumer-role
        principals from invoking administrator-only paths, including
        acknowledge_critical_alert (D-3 §§2.4, 6.1; PM-510 C-4)
    """

    @abstractmethod
    def get_core_pipeline_signals(self) -> CorePipelineSignals:
        """Return the current Core-supplied pipeline state signals (D-3 §8.1).

        Called to retrieve all Core-supplied eligibility, window, and
        kill-switch state before presenting administrator action surfaces.
        The concrete implementation must obtain these values from the Core;
        it must not compute or approximate them locally (D-3 §8.1).
        """

    @abstractmethod
    def get_pipeline_status(
        self, game_run_id: str | None = None
    ) -> PipelineStatusResult:
        """Return the current pipeline run status (D-3 §2.2; PM-503-A; PM-510 C-3).

        Accessible to both consumer and administrator roles (D-3 §§2.2, 6.1).
        The result is a PipelineStatusResult instance — opaque and read-only;
        its field composition, filtering, recency window, transport,
        serialization, and UI are Phase C decisions (D-3 §§2.2, 11).

        game_run_id: if supplied, returns status for the identified run; if
          None, returns status for the current or most recent active run. The
          recency window and filtering behavior when game_run_id is None are
          Phase C decisions (D-3 §2.2).

        Confirmed Core-determined C-10 (Edge/No Edge) and C-11 (Formal No
        Play) outcomes may be included in the returned PipelineStatusResult
        as read-only post-determination fields (D-3 §8.2; PM-510 C-5); the
        implementation must not accept input that influences, overrides, or
        pre-empts any C-10/C-11 determination.
        """

    @abstractmethod
    def get_alerts(self) -> tuple[Alert, ...]:
        """Return all current alerts ordered by event_timestamp (D-3 §§3.1–3.4).

        Both consumer and administrator surfaces receive all alerts.
        CRITICAL alerts persist until acknowledged via acknowledge_critical_alert;
        they must not be omitted until explicitly acknowledged by an authorized
        administrator (D-3 §3.3). The concrete implementation must not
        reclassify alert severity as received from the Core (D-3 §3.1).
        All returned CRITICAL Alert instances will have non-None game_run_id,
        sport, and alert_reference fields (enforced by Alert.__post_init__;
        D-3 §3.3; PM-510 C-1; PM-513 C-1, C-2).
        """

    @abstractmethod
    def acknowledge_critical_alert(self, alert_reference: str) -> None:
        """Submit a confirmed critical-alert acknowledgment to the Core (D-3 §4.4; PM-510 C-4).

        Administrator-only; the access-control layer must prevent consumer-role
        principals from invoking this method (D-3 §§2.4, 3.3, 6.1).

        alert_reference: opaque str identifier for the specific alert being
          acknowledged (D-3 §4.4; PM-503-B). The generation, persistence, and
          backing encoding of alert_reference values are Phase C decisions
          (D-3 §11).

        The Core writes the audit row for this acknowledgment; this method does
        not write audit rows directly (CO-4; D-3 §§4.4, 7.1). The audit row
        must carry administrator identity, a reference to the acknowledged alert,
        and the UTC timestamp of acknowledgment (D-3 §5.3).

        This method is not a pipeline action (D-3 §§4.1–4.3, §6.2); it does
        not trigger pipeline stage transitions or Core-to-adapter calls. If
        alert_reference is unknown or already acknowledged, the Core rejects
        and the rejection is audited (D-3 §7.2).
        """

    @abstractmethod
    def submit_admin_action(self, request: AdminActionRequest) -> AdminActionResponse:
        """Submit a confirmed administrator pipeline action request to the Core (D-3 §§4.1–4.3).

        The interface submits the request; the Core executes the action and
        writes the corresponding audit row (D-3 §5.3). The concrete
        implementation must enforce that request.confirmation_recorded is
        True at the surface before constructing the request (D-3 §6.2);
        AdminActionRequest.__post_init__ also enforces this invariant.

        Availability constraints that must be enforced before submission
        (D-3 §§4.1–4.2):
          CANCELLATION — available only when Core-supplied window is_open;
          MANUAL_STAGE_1_INITIATION — available only when Core signals
            ae_c3_5_eligible, not case_b_active, and not t_minus_60_reached;
            successful recovery means Core execution begun before T−60;
            Stage 1 execution itself may extend past T−60
            (D-3 §4.2; PM-501-D; PM-510 C-5).
        Rejected submissions are audited by the Core (D-3 §7.2).

        Critical-alert acknowledgment is submitted via acknowledge_critical_alert,
        not via this method (D-3 §§4.4, 6.2; PM-510 C-4).
        """

    @abstractmethod
    def read_audit_records(
        self, query: AuditRowQuery
    ) -> tuple[dict[str, Any], ...]:
        """Return oracle_immutability_audit rows matching the query (D-3 §5.1).

        Read-only; the interface has no write path to oracle_immutability_audit
        (CO-4; D-3 §5.1). The returned tuple reflects the complete, unfiltered
        append-only record for rows matching the query; the implementation must
        not suppress rows (D-3 §5.1).

        Row structure is a dict[str, Any] because D-4 governs audit row type
        definitions (D-3 §5.4); this module creates no row schemas.
        Consumer and administrator roles both have read access to the full
        record; no row-level restriction may reduce the record below the
        D-3 §5.1 completeness requirement (D-3 §5.2).
        """
