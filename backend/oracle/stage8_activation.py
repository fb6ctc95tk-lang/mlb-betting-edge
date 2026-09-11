"""Stage 8 — evidence-safe activation-window logic (Core-side; network/DB/clock-FREE).

C1 FULL (PM-1067 / PM-1069 / PM-1071): Stage 8 performs a *procedural* admission of a game
into the activation window, bound solely to the immutable Stage 7 frozen Final-Analysis
evidence identity. This module performs NO network, DB, or clock access: the Orchestrator
supplies every input (including the fresh decision_time) and owns the transaction
(DCR-W5-001). It computes the deterministic activation identity, classifies the cutoff
relationship, and decides the strict before-cutoff gate.

Epistemic discipline: admission establishes NO bet, market edge, official lineup
confirmation, source/provider freshness, or betting readiness, and computes no analytical
value. It does NOT revalidate live Stage-5/6/provider inputs; it binds only the frozen
Stage 7 identity. A historical admission (EXACT_REPLAY) is not perpetual permission after
cutoff and is not proof of current eligibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

# --- Caller-visible outcomes -------------------------------------------------
WINDOW_OPENED = "WINDOW_OPENED"
EXACT_REPLAY = "EXACT_REPLAY"
CHANGED_PROVENANCE = "CHANGED_PROVENANCE"
INELIGIBLE = "INELIGIBLE"
UNAVAILABLE_INPUTS = "UNAVAILABLE_INPUTS"

# --- Bounded reason codes ----------------------------------------------------
REASON_NOT_IN_SLATE = "not_in_slate"
REASON_NOT_IN_FINAL_ANALYSIS = "not_in_final_analysis"
REASON_NO_STAGE7_FINAL_RECORD = "no_stage7_final_record"
REASON_SLATE_NOT_OPEN_FOR_ADMISSION = "slate_not_open_for_admission"
REASON_AT_OR_AFTER_CUTOFF = "at_or_after_cutoff"
REASON_CUTOFF_MISSING_OR_INVALID = "cutoff_missing_or_invalid"
REASON_UNREADABLE_COMPARISON_INPUTS = "unreadable_comparison_inputs"

# --- Cutoff relationship (provenance only; admitted rows are always 'before') -
CUTOFF_BEFORE = "before"
CUTOFF_EQUAL = "equal"
CUTOFF_AFTER = "after"

# --- Standing, honest admission limitations (never an analytical/readiness claim) -
_STANDING_LIMITATIONS: tuple[str, ...] = (
    "procedural_admission_only_not_a_play",
    "no_market_edge_asserted",
    "not_official_lineup_confirmation",
    "not_source_freshness_or_betting_readiness",
    "bound_to_frozen_stage7_evidence__no_live_revalidation",
    "historical_admission_not_perpetual_permission_after_cutoff",
)


@dataclass(frozen=True)
class Stage8ActivationResult:
    """Explicit, immutable, caller-visible per-game Stage 8 outcome (PM-1067/1069/1071).

    Distinguishable without parsing logs or querying the DB. It reports what Stage 8 did;
    it computes no analytical value and makes no betting-readiness claim.
    """

    game_run_id: str
    outcome: str
    reason: str | None = None
    activation_identity: str | None = None
    stage7_bound_input_identity: str | None = None
    cutoff_relationship: str | None = None
    differing_inputs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def standing_limitations() -> tuple[str, ...]:
    """The honest limitation set attached to every admission and replay result."""
    return _STANDING_LIMITATIONS


def is_timezone_aware(dt: object) -> bool:
    """True iff dt is a timezone-aware datetime (offset-bearing)."""
    return (
        isinstance(dt, datetime)
        and dt.tzinfo is not None
        and dt.tzinfo.utcoffset(dt) is not None
    )


def is_before_cutoff(decision_time: object, scheduled_cutoff_at: object) -> bool:
    """True iff both timestamps are timezone-aware and decision_time < scheduled_cutoff_at.

    Strict: equality is NOT before-cutoff (equality/after rejects admission). Timezone-naive
    or non-datetime values are invalid and never silently coerced (the caller maps an invalid
    cutoff to UNAVAILABLE_INPUTS before calling this).
    """
    if not (is_timezone_aware(decision_time) and is_timezone_aware(scheduled_cutoff_at)):
        return False
    return decision_time < scheduled_cutoff_at


def cutoff_relationship(decision_time: object, scheduled_cutoff_at: object) -> str | None:
    """Classify decision_time vs the scheduled cutoff as before/equal/after (provenance only).

    Returns None if either timestamp is not timezone-aware. This relationship never fires the
    cutoff; for an admitted row it is always 'before' (the strict C4 gate).
    """
    if not (is_timezone_aware(decision_time) and is_timezone_aware(scheduled_cutoff_at)):
        return None
    if decision_time < scheduled_cutoff_at:
        return CUTOFF_BEFORE
    if decision_time == scheduled_cutoff_at:
        return CUTOFF_EQUAL
    return CUTOFF_AFTER


def compute_activation_identity(game_run_id: str, stage7_bound_input_identity: str) -> str:
    """Deterministic content-addressed admission identity bound to the frozen Stage 7 evidence.

    Bound to (game_run_id, stage7_bound_input_identity) ONLY — never to live Stage-5/6/provider
    inputs. Because the Stage 7 record is immutable, this identity is stable over time; time
    passing alone never changes it (so replay is EXACT_REPLAY, not CHANGED_PROVENANCE).
    """
    material = {
        "game_run_id": game_run_id,
        "stage7_bound_input_identity": stage7_bound_input_identity,
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"S8A-{game_run_id}-{digest}"
