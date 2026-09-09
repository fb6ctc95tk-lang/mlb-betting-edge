"""Stage 5 — Multi-model pipeline coordinator (Core-side; sport-neutral shell).

Runs the ratified four-engine MVP (GSE, MVE, ODG, SRL) over a slate of games
and produces one opaque, versioned ``Stage5Result`` per game for the
Orchestrator to persist. This module performs no database, network, or clock
access: inputs (including ``computed_at``) are supplied by the Orchestrator,
keeping Core transaction ownership and determinism intact (DCR-W5-001).

Engine analytical content is sport-specific and lives in
``backend.oracle.mlb_intelligence``; Core handles the aggregate result as a
versioned opaque record (PM-753 §3.3 Core purity). PHIE and CE are deferred
(PM-1007 D-2) and are neither invoked nor represented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.oracle.mlb_intelligence import GameEngineInput
from backend.oracle.mlb_intelligence.gse import evaluate_gse
from backend.oracle.mlb_intelligence.mve import evaluate_mve
from backend.oracle.mlb_intelligence.odg import evaluate_odg
from backend.oracle.mlb_intelligence.srl import SRLGameInput, rank_slate

PIPELINE_MODEL_VERSION: str = "stage5-mvp-v1"

# The four engines composing the ratified Stage 5 MVP (PM-1007 D-2).
ENGINE_SET: tuple[str, ...] = ("GSE", "MVE", "ODG", "SRL")


@dataclass(frozen=True)
class Stage5Result:
    """Opaque aggregate four-engine result persisted by Core."""

    stage5_result_id: str
    game_run_id: str
    slate_run_id: str
    ecf_result_id: str
    data_version_id: str
    verdict: str
    engine_outputs: dict
    model_version: str
    computed_at: datetime

    def preliminary_output_payload(self) -> dict:
        """Consumer-visible Preliminary payload derived from the aggregate."""
        return {
            "stage5_result_id": self.stage5_result_id,
            "game_run_id": self.game_run_id,
            "verdict": self.verdict,
            "engine_set": list(ENGINE_SET),
            "model_version": self.model_version,
        }


def run_stage5_pipeline(
    slate_run_id: str,
    inputs: list[GameEngineInput],
    computed_at: datetime,
) -> dict[str, Stage5Result]:
    """Execute the four-engine pipeline across the slate.

    Per-game GSE and MVE run first; SRL ranks across the whole slate; ODG then
    issues the per-game verdict. Returns a game_run_id -> Stage5Result mapping.
    Deterministic for a given (inputs, computed_at).
    """
    per_game: dict[str, dict] = {}
    srl_inputs: list[SRLGameInput] = []

    for item in inputs:
        gse = evaluate_gse(item.ecf_score, item.ecf_components, item.preliminary_payload)
        mve = evaluate_mve(
            ecf_score=item.ecf_score,
            script_confidence=gse.script_confidence,
            market_moneyline=item.market_moneyline,
        )
        per_game[item.game_run_id] = {"item": item, "gse": gse, "mve": mve}
        srl_inputs.append(
            SRLGameInput(
                game_run_id=item.game_run_id,
                ecf_score=item.ecf_score,
                script_confidence=gse.script_confidence,
                edge_percentage_points=mve.edge_percentage_points,
            )
        )

    srl_map = rank_slate(srl_inputs)

    results: dict[str, Stage5Result] = {}
    for game_run_id, parts in per_game.items():
        item: GameEngineInput = parts["item"]
        gse = parts["gse"]
        mve = parts["mve"]
        srl = srl_map[game_run_id]

        odg = evaluate_odg(
            ecf_score=item.ecf_score,
            script_confidence=gse.script_confidence,
            mve_edge_assessment=mve.edge_assessment,
            mve_edge_percentage_points=mve.edge_percentage_points,
            inherited_limitations=tuple(gse.confidence_limitations) + tuple(mve.confidence_limitations),
        )

        stage5_result_id = f"S5R-{game_run_id}-{int(computed_at.timestamp() * 1000)}"
        engine_outputs = {
            "gse": gse.as_dict(),
            "mve": mve.as_dict(),
            "odg": odg.as_dict(),
            "srl": srl.as_dict(),
        }
        results[game_run_id] = Stage5Result(
            stage5_result_id=stage5_result_id,
            game_run_id=game_run_id,
            slate_run_id=slate_run_id,
            ecf_result_id=item.ecf_result_id,
            data_version_id=item.data_version_id,
            verdict=odg.verdict,
            engine_outputs=engine_outputs,
            model_version=PIPELINE_MODEL_VERSION,
            computed_at=computed_at,
        )
    return results
