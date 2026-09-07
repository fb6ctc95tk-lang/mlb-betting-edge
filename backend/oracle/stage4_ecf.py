"""Stage 4 — Structural ECF v1 Engine (Core-side; sport-neutral; no DB access).

Formula: ecf_score = min(1.0, (data_completeness * 0.40) +
                              (data_freshness * 0.30) +
                              (data_payload_density * 0.30))

Authorized by PM-867 / Authorities A+B; scope SHA F3BF406F...
OPEN-ECF resolution from PM-855.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

FRESHNESS_WINDOW_SECONDS: int = 14400
MIN_EXPECTED_FIELDS: int = 5
MODEL_VERSION: str = "structural-ecf-v1"


@dataclass(frozen=True)
class ECFComponentScores:
    data_completeness: float
    data_freshness: float
    data_payload_density: float


@dataclass(frozen=True)
class ECFResult:
    ecf_result_id: str
    ecf_score: float
    components: ECFComponentScores
    model_version: str
    computed_at: datetime
    data_version_id: str


def compute_ecf(
    game_run_id: str,
    data_version_id: str,
    raw_payload: dict,
    gathered_at: datetime,
    computed_at: datetime,
) -> ECFResult:
    """Compute Structural ECF v1 score from raw_payload and gathered_at timestamp.

    Args:
        game_run_id: Game Analysis Run ID (used to generate ecf_result_id).
        data_version_id: Data version identifier for this calculation.
        raw_payload: Payload dict from oracle_preliminary_data.
        gathered_at: UTC timestamp when the data was gathered.
        computed_at: UTC timestamp when computation is performed (freshness reference).

    Returns:
        ECFResult with ecf_result_id, ecf_score in [0.0, 1.0], components,
        model_version, computed_at, and data_version_id.
    """
    data_completeness = _compute_data_completeness(raw_payload)
    data_freshness = _compute_data_freshness(gathered_at, computed_at)
    data_payload_density = _compute_data_payload_density(raw_payload)

    ecf_score = min(
        1.0,
        (data_completeness * 0.40)
        + (data_freshness * 0.30)
        + (data_payload_density * 0.30),
    )

    ecf_result_id = f"ECFR-{game_run_id}-{int(computed_at.timestamp() * 1000)}"

    return ECFResult(
        ecf_result_id=ecf_result_id,
        ecf_score=ecf_score,
        components=ECFComponentScores(
            data_completeness=data_completeness,
            data_freshness=data_freshness,
            data_payload_density=data_payload_density,
        ),
        model_version=MODEL_VERSION,
        computed_at=computed_at,
        data_version_id=data_version_id,
    )


def _compute_data_completeness(raw_payload: dict) -> float:
    if not isinstance(raw_payload, dict):
        return 0.0
    total = len(raw_payload)
    non_empty = sum(1 for v in raw_payload.values() if v is not None and v != "")
    return non_empty / max(total, 1)


def _compute_data_freshness(gathered_at: datetime, reference_time: datetime) -> float:
    if gathered_at.tzinfo is None:
        gathered_at = gathered_at.replace(tzinfo=timezone.utc)
    age_seconds = (reference_time - gathered_at).total_seconds()
    if age_seconds <= 0:
        return 1.0
    return max(0.0, 1.0 - (age_seconds / FRESHNESS_WINDOW_SECONDS))


def _compute_data_payload_density(raw_payload: dict) -> float:
    if not isinstance(raw_payload, dict):
        return 0.0
    return min(1.0, len(raw_payload) / MIN_EXPECTED_FIELDS)
