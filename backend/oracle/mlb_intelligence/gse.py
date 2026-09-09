"""GSE — Game Script Expectation engine (Stage 5 MVP; sport-specific, MLB).

Produces a structured run-environment / game-script expectation from the
data currently integrated in the Oracle Stage 5 path: the Stage 4 ECF result
(a data-certainty signal) and the Stage 3 preliminary payload (confirmed
probable-pitcher matchup). Deterministic and side-effect-free.

Confidence limitations are reported explicitly for inputs that PM-1007 names
for the full engine but that are not yet wired into the Oracle Stage 5 data
path (confirmed lineups, bullpen context, weather). This is an honest MVP
boundary, not a stub: outputs are derived from real inputs, never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION: str = "gse-mvp-v1"

# Inputs named by PM-1007 for the full GSE but not yet integrated into the
# Oracle Stage 5 data path (Stage 3 gathers schedule + probable pitchers only).
_UNWIRED_INPUTS: tuple[str, ...] = (
    "confirmed_lineup_not_integrated",
    "bullpen_context_not_integrated",
    "weather_not_integrated",
)


@dataclass(frozen=True)
class GSEResult:
    engine: str
    model_version: str
    pitching_matchup_established: bool
    script_profile: str
    script_confidence: float
    findings: dict
    confidence_limitations: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "model_version": self.model_version,
            "pitching_matchup_established": self.pitching_matchup_established,
            "script_profile": self.script_profile,
            "script_confidence": self.script_confidence,
            "findings": self.findings,
            "confidence_limitations": list(self.confidence_limitations),
        }


def evaluate_gse(
    ecf_score: float,
    ecf_components: dict,
    preliminary_payload: dict,
) -> GSEResult:
    """Compute the MLB game-script expectation deterministically.

    script_confidence blends the Stage 4 ECF score (overall data certainty)
    with whether both probable starting pitchers are confirmed in the Stage 3
    payload. The result is bounded to [0, 1] and fully determined by inputs.
    """
    home_pitcher = str(preliminary_payload.get("home_pitcher", "") or "").strip()
    away_pitcher = str(preliminary_payload.get("away_pitcher", "") or "").strip()
    matchup_established = bool(home_pitcher) and bool(away_pitcher)

    clamped_ecf = _clamp01(ecf_score)
    matchup_signal = 1.0 if matchup_established else 0.0
    script_confidence = round(0.60 * clamped_ecf + 0.40 * matchup_signal, 4)

    if not matchup_established:
        script_profile = "UNCERTAIN_MATCHUP"
    elif script_confidence >= 0.66:
        script_profile = "PITCHING_ESTABLISHED"
    elif script_confidence >= 0.40:
        script_profile = "BALANCED"
    else:
        script_profile = "LOW_CONFIDENCE"

    findings = {
        "home_pitcher": home_pitcher,
        "away_pitcher": away_pitcher,
        "ecf_score": clamped_ecf,
        "data_completeness": _clamp01(
            float(ecf_components.get("data_completeness", 0.0))
        ),
        "data_freshness": _clamp01(
            float(ecf_components.get("data_freshness", 0.0))
        ),
    }

    return GSEResult(
        engine="GSE",
        model_version=MODEL_VERSION,
        pitching_matchup_established=matchup_established,
        script_profile=script_profile,
        script_confidence=script_confidence,
        findings=findings,
        confidence_limitations=_UNWIRED_INPUTS,
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
