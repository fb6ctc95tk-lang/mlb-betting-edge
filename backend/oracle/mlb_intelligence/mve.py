"""MVE — Market Value Engine (Stage 5 MVP; sport-specific, MLB).

Compares a model-derived fair probability against a market moneyline implied
probability and produces a structured edge assessment. Deterministic and
side-effect-free — the engine performs no network I/O and never fetches odds
itself; a market price is supplied as an explicit input.

MVP data boundary (disclosed, not a stub): no live odds provider is wired into
the Oracle Stage 5 data path, so ``market_moneyline`` is normally ``None`` and
the engine returns a truthful ``INSUFFICIENT_MARKET_DATA`` assessment rather
than fabricating an edge. When a moneyline is supplied (tests, or a future
wired source), the EDGE / NO_EDGE branches compute real implied-probability
math. The model fair probability is an explicitly data-limited prior derived
from ECF certainty and GSE confidence; it is bounded near 0.5 so the MVP never
pretends strong conviction.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION: str = "mve-mvp-v1"

# Minimum model-vs-market gap (percentage points) to call a positive edge.
EDGE_THRESHOLD_PP: float = 3.0

# Bound the data-limited model prior near 0.5 (no team-strength model in MVP).
_MAX_PRIOR_DEVIATION: float = 0.15


@dataclass(frozen=True)
class MVEResult:
    engine: str
    model_version: str
    selected_side: str
    market_price_available: bool
    model_fair_probability: float
    market_implied_probability: float | None
    edge_percentage_points: float | None
    edge_assessment: str
    findings: dict
    confidence_limitations: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "model_version": self.model_version,
            "selected_side": self.selected_side,
            "market_price_available": self.market_price_available,
            "model_fair_probability": self.model_fair_probability,
            "market_implied_probability": self.market_implied_probability,
            "edge_percentage_points": self.edge_percentage_points,
            "edge_assessment": self.edge_assessment,
            "findings": self.findings,
            "confidence_limitations": list(self.confidence_limitations),
        }


def evaluate_mve(
    ecf_score: float,
    script_confidence: float,
    market_moneyline: dict | None = None,
    selected_side: str = "home",
) -> MVEResult:
    """Produce a structured moneyline edge assessment (deterministic).

    Args:
        ecf_score: Stage 4 ECF score (data-certainty signal), [0, 1].
        script_confidence: GSE script confidence, [0, 1].
        market_moneyline: optional dict of American odds keyed by side, e.g.
            {"home": -135, "away": +115}. None in the current MVP data path.
        selected_side: side to assess ("home" or "away"); default "home".
    """
    model_fair_probability = _model_fair_probability(ecf_score, script_confidence)

    limitations: list[str] = [
        "no_live_odds_provider_wired",
        "data_limited_model_prior",
    ]

    if not market_moneyline or selected_side not in market_moneyline:
        return MVEResult(
            engine="MVE",
            model_version=MODEL_VERSION,
            selected_side=selected_side,
            market_price_available=False,
            model_fair_probability=model_fair_probability,
            market_implied_probability=None,
            edge_percentage_points=None,
            edge_assessment="INSUFFICIENT_MARKET_DATA",
            findings={"reason": "no market moneyline supplied for selected side"},
            confidence_limitations=tuple(limitations),
        )

    implied = _american_to_implied_probability(int(market_moneyline[selected_side]))
    edge_pp = round((model_fair_probability - implied) * 100.0, 4)
    edge_assessment = "EDGE" if edge_pp >= EDGE_THRESHOLD_PP else "NO_EDGE"

    return MVEResult(
        engine="MVE",
        model_version=MODEL_VERSION,
        selected_side=selected_side,
        market_price_available=True,
        model_fair_probability=model_fair_probability,
        market_implied_probability=round(implied, 4),
        edge_percentage_points=edge_pp,
        edge_assessment=edge_assessment,
        findings={
            "moneyline": int(market_moneyline[selected_side]),
            "edge_threshold_pp": EDGE_THRESHOLD_PP,
        },
        confidence_limitations=tuple(limitations),
    )


def _model_fair_probability(ecf_score: float, script_confidence: float) -> float:
    """Data-limited fair-probability prior bounded near 0.5.

    With no team-strength model in the MVP, the fair probability is a neutral
    0.5 nudged by a bounded function of ECF certainty and GSE confidence.
    """
    signal = (_clamp01(ecf_score) + _clamp01(script_confidence)) / 2.0 - 0.5
    deviation = max(-_MAX_PRIOR_DEVIATION, min(_MAX_PRIOR_DEVIATION, signal * _MAX_PRIOR_DEVIATION * 2.0))
    return round(0.5 + deviation, 4)


def _american_to_implied_probability(odds: int) -> float:
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
