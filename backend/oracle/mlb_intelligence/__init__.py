"""Oracle Inc-3 — MLB Intelligence engines (Stage 5 four-engine MVP).

Sport-specific analytical engines for the Stage 5 multi-model pipeline
(PM-1007 D-2 ratified minimum): GSE, MVE, ODG, SRL. Per PM-753 §3.3 Core
purity, all sport-specific analytical content lives here, outside Core; the
Orchestrator (Core) consumes the aggregate result opaquely.

Every engine is a pure, deterministic, side-effect-free function over its
explicit inputs. Engines never access the database, network, or clock. They
report honest ``confidence_limitations`` for inputs not yet integrated into
the Oracle Stage 5 data path (e.g., live odds, confirmed lineups, weather,
bullpen). No PHIE or CE engine is implemented (deferred per PM-1007 D-2); no
placeholder, fabricated output, or false completion is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GameEngineInput:
    """Immutable per-game input bundle handed to the Stage 5 engines.

    Contains only data already available in the Oracle Stage 5 path: the
    consumed Stage 4 ECF result, the Stage 3 preliminary payload, and game
    metadata. ``market_moneyline`` is an optional pass-through for a future
    wired odds source; it is ``None`` in the current MVP data path.
    """

    game_run_id: str
    ecf_result_id: str
    data_version_id: str
    ecf_score: float
    ecf_components: dict
    ecf_model_version: str
    preliminary_payload: dict
    first_pitch_time: datetime
    market_moneyline: dict | None = None


__all__ = ["GameEngineInput"]
