"""Stage 7 — evidence-safe final-analysis logic (Core-side; network/DB/clock-FREE).

Option A (PM-1047 / PM-1049): finalize the existing immutable Stage 5 scalar verdict with
Stage 6 observation provenance. This module performs NO network, DB, or clock access: the
Orchestrator supplies every input (including assessment_at) and owns the transaction
(DCR-W5-001). It computes the deterministic bound-input identity, validates the observation
timestamp, classifies the cutoff relationship, and reports differing bound inputs.

Epistemic discipline: Stage 7 never adjusts the Stage 5 prediction, never increases
confidence, and never upgrades observed/PROBABLE data to official confirmation. "Final"
denotes a frozen, versioned restatement of the Stage 5 verdict bound to its provenance; it
does NOT establish official lineup confirmation, analytical freshness, or betting readiness.
observed_at measures Stage 6 retrieval/assessment time, not provider-origin freshness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Caller-visible outcomes -------------------------------------------------
FIRST_FINALIZATION = "FIRST_FINALIZATION"
EXACT_REPLAY = "EXACT_REPLAY"
CHANGED_PROVENANCE = "CHANGED_PROVENANCE"
INELIGIBLE = "INELIGIBLE"
UNAVAILABLE_INPUTS = "UNAVAILABLE_INPUTS"

# --- Bounded reason codes ----------------------------------------------------
REASON_NOT_IN_LINEUP_MONITORING = "not_in_lineup_monitoring"
REASON_NO_STAGE5_RESULT = "no_stage5_result"
REASON_NO_SCHEDULED_CUTOFF = "no_scheduled_cutoff"
REASON_NO_CANONICAL_OBSERVATION = "no_canonical_observation"
REASON_INVALID_OBSERVATION_TIMESTAMP = "invalid_observation_timestamp"
REASON_FUTURE_OBSERVATION_TIMESTAMP = "future_observation_timestamp"
REASON_UNREADABLE_COMPARISON_INPUTS = "unreadable_comparison_inputs"

# --- Cutoff relationship (provenance only; never an eligibility gate) --------
CUTOFF_BEFORE = "before"
CUTOFF_EQUAL = "equal"
CUTOFF_AFTER = "after"

# --- Standing, honest evidence limitations (never adjust the Stage 5 output) -
_STANDING_LIMITATIONS: tuple[str, ...] = (
    "confirmed_lineup_not_integrated",
    "starting_pitchers_probable_not_confirmed",
    "not_official_lineup_confirmation",
    "not_analytical_freshness_or_betting_readiness",
    "no_confidence_increase__stage6_provenance_only",
    "observed_snapshot_not_proof_of_current_lineup_state",
    "exact_replay_not_proof_latest_provider_attempt_succeeded_or_conditions_current",
)

# Order of the bound material inputs that define replay identity (PM-1049).
_BOUND_INPUT_KEYS: tuple[str, ...] = (
    "stage5_result_id",
    "data_version_id",
    "policy_version_id",
    "scheduled_cutoff_at",
    "stage6_snapshot_identity",
)


@dataclass(frozen=True)
class Stage7FinalResult:
    """Explicit, immutable, caller-visible per-game Stage 7 outcome (PM-1047/PM-1049).

    Distinguishable without parsing logs or querying the DB. It reports what Stage 7 did;
    it changes no Stage 5 analytical value and no product meaning.
    """

    game_run_id: str
    outcome: str
    reason: str | None = None
    bound_input_identity: str | None = None
    stage5_result_id: str | None = None
    verdict: str | None = None
    stage6_snapshot_identity: str | None = None
    cutoff_relationship: str | None = None
    differing_inputs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def standing_limitations() -> tuple[str, ...]:
    """The honest limitation set attached to every finalization and replay result."""
    return _STANDING_LIMITATIONS


def is_timezone_aware(dt: object) -> bool:
    """True iff dt is a timezone-aware datetime (offset-bearing)."""
    return (
        isinstance(dt, datetime)
        and dt.tzinfo is not None
        and dt.tzinfo.utcoffset(dt) is not None
    )


def is_valid_non_future_observed_at(observed_at: object, assessment_at: object) -> bool:
    """True iff both timestamps are timezone-aware and observed_at <= assessment_at.

    Exact equality is non-future and therefore valid. Timezone-naive or non-datetime
    values are invalid (never silently coerced).
    """
    if not (is_timezone_aware(observed_at) and is_timezone_aware(assessment_at)):
        return False
    return observed_at <= assessment_at


def cutoff_relationship(observed_at: object, scheduled_cutoff_at: object) -> str | None:
    """Classify observed_at vs the scheduled cutoff as before/equal/after (provenance only).

    Returns None if either timestamp is not timezone-aware. This relationship never gates
    eligibility and never fires the cutoff.
    """
    if not (is_timezone_aware(observed_at) and is_timezone_aware(scheduled_cutoff_at)):
        return None
    if observed_at < scheduled_cutoff_at:
        return CUTOFF_BEFORE
    if observed_at == scheduled_cutoff_at:
        return CUTOFF_EQUAL
    return CUTOFF_AFTER


def _normalize(value: object) -> object:
    """Deterministically normalize a bound-input value for hashing/comparison."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def bound_inputs(
    stage5_result_id: str,
    data_version_id: str,
    policy_version_id: str,
    scheduled_cutoff_at: object,
    stage6_snapshot_identity: str | None,
) -> dict:
    """Assemble the normalized bound-input mapping (all material inputs, not just Stage 5)."""
    return {
        "stage5_result_id": _normalize(stage5_result_id),
        "data_version_id": _normalize(data_version_id),
        "policy_version_id": _normalize(policy_version_id),
        "scheduled_cutoff_at": _normalize(scheduled_cutoff_at),
        "stage6_snapshot_identity": _normalize(stage6_snapshot_identity),
    }


def compute_bound_input_identity(game_run_id: str, inputs: dict) -> str:
    """Deterministic content-addressed identity over all bound material inputs (PM-1049)."""
    material = {"game_run_id": game_run_id, **{k: inputs.get(k) for k in _BOUND_INPUT_KEYS}}
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"S7F-{game_run_id}-{digest}"


def differing_bound_inputs(current: dict, stored: dict) -> tuple[str, ...]:
    """Return the bound-input keys whose current normalized value differs from the stored one."""
    return tuple(
        k for k in _BOUND_INPUT_KEYS if current.get(k) != stored.get(k)
    )
