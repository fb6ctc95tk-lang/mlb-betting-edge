"""SRL — Slate Ranking Logic (Stage 5 MVP; sport-specific, MLB).

Ranks eligible games across the slate and assigns each an ordered composite
score, rank, and tier. Deterministic and side-effect-free: given the same set
of per-game inputs, the ranking and tiers are identical (ties broken by
game_run_id for stable ordering).

The composite score blends ECF certainty, GSE script confidence, and MVE edge
(0 when market data is insufficient). Tiers split the ranked slate into
TOP / MIDDLE / BOTTOM thirds.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION: str = "srl-mvp-v1"

TIER_TOP: str = "TOP"
TIER_MIDDLE: str = "MIDDLE"
TIER_BOTTOM: str = "BOTTOM"


@dataclass(frozen=True)
class SRLGameInput:
    game_run_id: str
    ecf_score: float
    script_confidence: float
    edge_percentage_points: float | None


@dataclass(frozen=True)
class SRLResult:
    engine: str
    model_version: str
    composite_score: float
    rank: int
    tier: str
    slate_size: int

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "model_version": self.model_version,
            "composite_score": self.composite_score,
            "rank": self.rank,
            "tier": self.tier,
            "slate_size": self.slate_size,
        }


def compute_composite_score(
    ecf_score: float,
    script_confidence: float,
    edge_percentage_points: float | None,
) -> float:
    """Deterministic per-game composite in [0, 1]."""
    edge_component = 0.0
    if edge_percentage_points is not None:
        # Normalize edge (percentage points) into [0, 1] at a 10pp ceiling.
        edge_component = max(0.0, min(1.0, edge_percentage_points / 10.0))
    return round(
        0.50 * _clamp01(ecf_score)
        + 0.30 * _clamp01(script_confidence)
        + 0.20 * edge_component,
        4,
    )


def rank_slate(entries: list[SRLGameInput]) -> dict[str, SRLResult]:
    """Rank the slate and return a game_run_id -> SRLResult mapping.

    Ranking is by composite score descending; ties are broken by game_run_id
    ascending for deterministic, stable ordering. Tiers split into thirds.
    """
    scored = [
        (
            e.game_run_id,
            compute_composite_score(e.ecf_score, e.script_confidence, e.edge_percentage_points),
        )
        for e in entries
    ]
    # Descending score, then ascending game_run_id for stable determinism.
    scored.sort(key=lambda pair: (-pair[1], pair[0]))

    slate_size = len(scored)
    results: dict[str, SRLResult] = {}
    for index, (game_run_id, composite) in enumerate(scored):
        rank = index + 1
        results[game_run_id] = SRLResult(
            engine="SRL",
            model_version=MODEL_VERSION,
            composite_score=composite,
            rank=rank,
            tier=_tier_for_rank(rank, slate_size),
            slate_size=slate_size,
        )
    return results


def _tier_for_rank(rank: int, slate_size: int) -> str:
    if slate_size <= 0:
        return TIER_BOTTOM
    # At least one game in TOP and one in BOTTOM; the remainder is MIDDLE.
    top_count = max(1, slate_size // 3)
    bottom_start = slate_size - max(1, slate_size // 3) + 1
    if rank <= top_count:
        return TIER_TOP
    if rank >= bottom_start:
        return TIER_BOTTOM
    return TIER_MIDDLE


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
