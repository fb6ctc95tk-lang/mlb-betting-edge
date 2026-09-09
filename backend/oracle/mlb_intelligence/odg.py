"""ODG — Oracle Decision Gate (Stage 5 MVP; sport-specific, MLB).

Consumes the GSE and MVE outputs (plus the ECF score) and issues exactly one
governed verdict — ``Activate``, ``Conditional``, or ``No Play`` — with
machine-readable reasons and propagated confidence limitations. Deterministic
and side-effect-free.

The gate is honest about data limits: when MVE reports insufficient market
data (the normal MVP path), the gate returns ``No Play`` with the reason
``insufficient_market_data``. This is a real analytical verdict, not a stub or
fabricated result.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION: str = "odg-mvp-v1"

VERDICT_ACTIVATE: str = "Activate"
VERDICT_CONDITIONAL: str = "Conditional"
VERDICT_NO_PLAY: str = "No Play"

_MIN_SCRIPT_CONFIDENCE: float = 0.40
_ACTIVATE_SCRIPT_CONFIDENCE: float = 0.66


@dataclass(frozen=True)
class ODGResult:
    engine: str
    model_version: str
    verdict: str
    reasons: tuple[str, ...]
    gate_scores: dict
    confidence_limitations: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "model_version": self.model_version,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "gate_scores": self.gate_scores,
            "confidence_limitations": list(self.confidence_limitations),
        }


def evaluate_odg(
    ecf_score: float,
    script_confidence: float,
    mve_edge_assessment: str,
    mve_edge_percentage_points: float | None,
    inherited_limitations: tuple[str, ...] = (),
) -> ODGResult:
    """Issue exactly one governed gate verdict deterministically."""
    gate_scores = {
        "ecf_score": _clamp01(ecf_score),
        "script_confidence": _clamp01(script_confidence),
        "mve_edge_assessment": mve_edge_assessment,
        "mve_edge_percentage_points": mve_edge_percentage_points,
    }
    limitations = tuple(dict.fromkeys(inherited_limitations))

    if mve_edge_assessment == "INSUFFICIENT_MARKET_DATA":
        return _result(VERDICT_NO_PLAY, ("insufficient_market_data",), gate_scores, limitations)

    if _clamp01(script_confidence) < _MIN_SCRIPT_CONFIDENCE:
        return _result(VERDICT_NO_PLAY, ("low_script_confidence",), gate_scores, limitations)

    if mve_edge_assessment == "NO_EDGE":
        return _result(VERDICT_NO_PLAY, ("no_market_edge",), gate_scores, limitations)

    if mve_edge_assessment == "EDGE":
        if _clamp01(script_confidence) >= _ACTIVATE_SCRIPT_CONFIDENCE:
            return _result(
                VERDICT_ACTIVATE,
                ("positive_market_edge", "sufficient_script_confidence"),
                gate_scores,
                limitations,
            )
        return _result(
            VERDICT_CONDITIONAL,
            ("positive_market_edge", "conditional_script_confidence"),
            gate_scores,
            limitations,
        )

    # Unknown assessment value is treated conservatively as No Play.
    return _result(VERDICT_NO_PLAY, ("unrecognized_market_assessment",), gate_scores, limitations)


def _result(verdict, reasons, gate_scores, limitations) -> ODGResult:
    return ODGResult(
        engine="ODG",
        model_version=MODEL_VERSION,
        verdict=verdict,
        reasons=tuple(reasons),
        gate_scores=gate_scores,
        confidence_limitations=limitations,
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
