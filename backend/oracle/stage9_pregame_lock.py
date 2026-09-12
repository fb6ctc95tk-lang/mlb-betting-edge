"""Stage 9 — evidence-safe pregame-lock logic (Core-side; network/DB/clock-FREE).

FULL immutable per-game pregame lock (PM-1089 as corrected by PM-1091, finalized by PM-1092):
Stage 9 finalizes a game already admitted by Stage 8 into a *pregame lock*, bound to the
immutable Stage-8 admission provenance (its activation identity and the frozen Stage-7 bound
input identity). This module performs NO network, DB, or clock access: the Orchestrator supplies
every input (including the fresh post-wait decision_time) and owns the transaction (DCR-W5-001).
It computes the deterministic lock identity, classifies the cutoff relationship, and decides the
strict before-cutoff freeze boundary.

Epistemic discipline (do NOT expand freeze claims beyond PM-1092): the lock establishes NO bet,
market edge, official lineup confirmation, source/provider freshness, or betting readiness, and
computes no analytical value. It does NOT revalidate live Stage-5/6/provider inputs and does NOT
re-run Stage-8 admission eligibility; it binds only the frozen Stage-8/Stage-7 provenance. A
historical lock (EXACT_REPLAY) is not perpetual permission after cutoff and is not proof of
current eligibility. Stage 9 fires no cutoff, runs no scheduler, and invents no slate-closure
authority: an admission that cannot be locked in time simply leaves the slate incomplete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

# --- Caller-visible outcomes -------------------------------------------------
LOCKED = "LOCKED"
EXACT_REPLAY = "EXACT_REPLAY"
CHANGED_PROVENANCE = "CHANGED_PROVENANCE"
INELIGIBLE = "INELIGIBLE"
UNAVAILABLE_INPUTS = "UNAVAILABLE_INPUTS"

# --- Bounded reason codes ----------------------------------------------------
REASON_NOT_IN_SLATE = "not_in_slate"
REASON_SLATE_ALREADY_LOCKED = "slate_already_locked"
REASON_NO_ADMISSION = "no_admission"
REASON_NOT_ACTIVATION_ELIGIBLE = "not_activation_eligible"
REASON_AT_OR_AFTER_CUTOFF = "at_or_after_cutoff"
REASON_CUTOFF_MISSING_OR_INVALID = "cutoff_missing_or_invalid"
REASON_UNREADABLE_COMPARISON_INPUTS = "unreadable_comparison_inputs"

# --- Cutoff relationship (provenance only; locked rows are always 'before') ---
CUTOFF_BEFORE = "before"
CUTOFF_EQUAL = "equal"
CUTOFF_AFTER = "after"

# --- Standing, honest lock limitations (never an analytical/readiness claim) --
_STANDING_LIMITATIONS: tuple[str, ...] = (
    "pregame_lock_only_not_a_play",
    "no_market_edge_asserted",
    "not_official_lineup_confirmation",
    "not_source_freshness_or_betting_readiness",
    "bound_to_frozen_stage8_admission_and_stage7_evidence__no_live_revalidation",
    "historical_lock_not_perpetual_permission_after_cutoff",
)


@dataclass(frozen=True)
class Stage9LockResult:
    """Explicit, immutable, caller-visible per-game Stage 9 outcome.

    Distinguishable without parsing logs or querying the DB. It reports what Stage 9 did; it
    computes no analytical value and makes no betting-readiness claim.
    """

    game_run_id: str
    outcome: str
    reason: str | None = None
    lock_identity: str | None = None
    activation_identity: str | None = None
    stage7_bound_input_identity: str | None = None
    cutoff_relationship: str | None = None
    differing_inputs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def standing_limitations() -> tuple[str, ...]:
    """The honest limitation set attached to every lock and replay result."""
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

    Strict: equality is NOT before-cutoff (equality/after rejects the lock as INELIGIBLE).
    Timezone-naive or non-datetime values are invalid and never silently coerced (the caller
    maps an invalid cutoff to UNAVAILABLE_INPUTS before calling this).
    """
    if not (is_timezone_aware(decision_time) and is_timezone_aware(scheduled_cutoff_at)):
        return False
    return decision_time < scheduled_cutoff_at


def cutoff_relationship(decision_time: object, scheduled_cutoff_at: object) -> str | None:
    """Classify decision_time vs the scheduled cutoff as before/equal/after (provenance only).

    Returns None if either timestamp is not timezone-aware. This relationship never fires the
    cutoff; for a locked row it is always 'before' (the strict freeze boundary).
    """
    if not (is_timezone_aware(decision_time) and is_timezone_aware(scheduled_cutoff_at)):
        return None
    if decision_time < scheduled_cutoff_at:
        return CUTOFF_BEFORE
    if decision_time == scheduled_cutoff_at:
        return CUTOFF_EQUAL
    return CUTOFF_AFTER


def compute_lock_identity(
    game_run_id: str,
    activation_identity: str,
    stage7_bound_input_identity: str,
) -> str:
    """Deterministic content-addressed lock identity bound to the frozen Stage-8/Stage-7 provenance.

    Bound to (game_run_id, activation_identity, stage7_bound_input_identity) ONLY — never to live
    Stage-5/6/provider inputs. Because the Stage-8 admission and Stage-7 record are immutable, this
    identity is stable over time; time passing alone never changes it (so replay is EXACT_REPLAY,
    not CHANGED_PROVENANCE).
    """
    material = {
        "game_run_id": game_run_id,
        "activation_identity": activation_identity,
        "stage7_bound_input_identity": stage7_bound_input_identity,
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"S9L-{game_run_id}-{digest}"
