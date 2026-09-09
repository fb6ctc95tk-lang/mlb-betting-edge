"""Oracle Inc-1 — MLB Sport Module Adapter (N-2).

Concrete implementation of SportModuleAdapter for MLB via MLB Stats API.
Calls GET /api/v1/schedule for preliminary game data (real implementation;
authorized by PM-783/Authority B and PM-781/Authority A). No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from backend.oracle.adapter_interface import (
    AvailabilityStatus,
    CandidateChangeEvent,
    FinalizationStatus,
    FinalizationStatusCode,
    ObservationResponse,
    PreliminaryDataRecord,
    PreliminaryDataResponse,
    SportModuleAdapter,
    TimestampResponse,
    UnavailabilityReason,
)

# ---------------------------------------------------------------------------
# Stage 6 evidence-safe lineup observation (Inc-3+; PM-1029 Option B)
#
# Evidence-safe classification vocabulary. AUTHORITATIVELY_CONFIRMED is
# deliberately ABSENT here: the current public MLB provider cannot prove
# official confirmation, so this adapter must never produce that status
# (PM-1029). Structural completeness (e.g., a full 9-slot batting order) proves
# only that data was OBSERVED, never that MLB officially confirmed it. A
# probable pitcher is always PROBABLE.
# ---------------------------------------------------------------------------

LINEUP_UNAVAILABLE = "UNAVAILABLE"
LINEUP_PARTIAL = "PARTIAL"
LINEUP_OBSERVED_FULL = "OBSERVED_FULL"
PITCHER_PROBABLE = "PROBABLE"

# A complete observed MLB batting order is 9 slots. Used ONLY as an observed
# structural-completeness threshold, never as proof of official confirmation.
_EXPECTED_LINEUP_SIZE = 9
_LINEUP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class LineupObservation:
    """Normalized, evidence-safe lineup observation returned by the MLB adapter.

    All network access is confined to this adapter; consumers (stage6_lineup)
    operate only on this normalized output and perform no network activity.
    Ordered personId lists preserve the provider batting order. Pitcher entries
    carry an explicit epistemic_status which is always PROBABLE under the
    current provider contract.
    """

    game_id: str
    classification: str  # LINEUP_UNAVAILABLE | LINEUP_PARTIAL | LINEUP_OBSERVED_FULL
    home_order: tuple[int, ...] = ()
    away_order: tuple[int, ...] = ()
    home_pitcher: dict | None = None  # {"id": int, "epistemic_status": "PROBABLE"} | None
    away_pitcher: dict | None = None
    home_lineup_status: str = LINEUP_UNAVAILABLE
    away_lineup_status: str = LINEUP_UNAVAILABLE
    source: str = "mlb-statsapi-schedule-lineups"
    detail: str | None = None


class MLBAdapter(SportModuleAdapter):
    """MLB Sport Module Adapter — real MLB Stats API implementation.

    get_preliminary_data() calls statsapi.mlb.com; no API key required.
    """

    def get_availability(self) -> AvailabilityStatus:
        return AvailabilityStatus(available=True)

    def get_game_start_timestamp(self, game_id: str) -> TimestampResponse:
        return TimestampResponse(
            timestamp=datetime.now(tz=timezone.utc),
            availability=AvailabilityStatus(available=True),
        )

    def get_preliminary_data(self, game_id: str) -> PreliminaryDataResponse:
        url = "https://statsapi.mlb.com/api/v1/schedule"
        params = {"sportId": 1, "gamePk": game_id, "hydrate": "probablePitcher,team"}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            game = data["dates"][0]["games"][0]
            gathered_at = datetime.now(tz=timezone.utc)
            data_version_id = f"DV-{game_id}-{int(gathered_at.timestamp())}"
            raw_payload = {
                "external_game_id": str(game.get("gamePk", "")),
                "game_date": game.get("gameDate", ""),
                "status": game.get("status", {}).get("detailedState", ""),
                "home_team": game.get("teams", {}).get("home", {}).get("team", {}).get("abbreviation", ""),
                "away_team": game.get("teams", {}).get("away", {}).get("team", {}).get("abbreviation", ""),
                "home_pitcher": game.get("teams", {}).get("home", {}).get("probablePitcher", {}).get("fullName", ""),
                "away_pitcher": game.get("teams", {}).get("away", {}).get("probablePitcher", {}).get("fullName", ""),
            }
            record = PreliminaryDataRecord(
                game_id=game_id,
                data_version_id=data_version_id,
                gathered_at=gathered_at,
                source_system="mlb-statsapi",
                raw_payload=raw_payload,
            )
            return PreliminaryDataResponse(
                record=record,
                availability=AvailabilityStatus(available=True),
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return PreliminaryDataResponse(
                record=None,
                availability=AvailabilityStatus(
                    available=False,
                    reason=UnavailabilityReason.DATA_SOURCE_UNREACHABLE,
                ),
            )
        except requests.exceptions.HTTPError:
            return PreliminaryDataResponse(
                record=None,
                availability=AvailabilityStatus(
                    available=False,
                    reason=UnavailabilityReason.ERROR_RESPONSE,
                ),
            )
        except (IndexError, KeyError):
            return PreliminaryDataResponse(
                record=None,
                availability=AvailabilityStatus(
                    available=False,
                    reason=UnavailabilityReason.ADAPTER_INTERNAL_FAILURE,
                ),
            )

    def observe(self, game_id: str) -> ObservationResponse:
        return ObservationResponse(
            candidate_events=(),
            finalization_status=FinalizationStatus(code=FinalizationStatusCode.NO_EVENT),
            availability=AvailabilityStatus(available=True),
        )

    def observe_lineup(self, game_id: str) -> LineupObservation:
        """One synchronous, read-only, evidence-safe MLB lineup observation.

        GET-only public MLB Stats API (no key). All network access for Stage 6
        is contained here. Fails CLOSED: any network, HTTP, JSON, or structural
        error yields classification=UNAVAILABLE (never an exception to the
        caller, never fabricated data).

        Classification (evidence-safe; PM-1029):
          OBSERVED_FULL — both sides present a full ordered 9-slot batting order
            AND both probable pitchers are present. Proves the snapshot was
            OBSERVED, not that MLB officially confirmed it.
          PARTIAL — some lineup/pitcher data present but not complete on both
            sides.
          UNAVAILABLE — no usable lineup/pitcher evidence, or a fetch/parse
            failure.
        Pitchers are always PROBABLE. AUTHORITATIVELY_CONFIRMED is never
        produced. Lineup length/order/presence are used only for observed
        structural completeness, never as confirmation evidence.
        """
        url = "https://statsapi.mlb.com/api/v1/schedule"
        params = {
            "sportId": 1,
            "gamePk": game_id,
            "hydrate": "probablePitcher,lineups,team",
        }
        try:
            response = requests.get(url, params=params, timeout=_LINEUP_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            game = data["dates"][0]["games"][0]
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return LineupObservation(game_id=game_id, classification=LINEUP_UNAVAILABLE,
                                     detail="data source unreachable")
        except requests.exceptions.HTTPError:
            return LineupObservation(game_id=game_id, classification=LINEUP_UNAVAILABLE,
                                     detail="provider error response")
        except (IndexError, KeyError, ValueError):
            return LineupObservation(game_id=game_id, classification=LINEUP_UNAVAILABLE,
                                     detail="no game / unparseable provider response")

        lineups = game.get("lineups", {}) or {}
        home_order = self._normalize_order(lineups.get("homePlayers", []))
        away_order = self._normalize_order(lineups.get("awayPlayers", []))
        teams = game.get("teams", {}) or {}
        home_pitcher = self._normalize_probable(teams.get("home", {}))
        away_pitcher = self._normalize_probable(teams.get("away", {}))

        home_status = self._side_status(home_order)
        away_status = self._side_status(away_order)

        both_full = (
            len(home_order) == _EXPECTED_LINEUP_SIZE
            and len(away_order) == _EXPECTED_LINEUP_SIZE
            and home_pitcher is not None
            and away_pitcher is not None
        )
        any_data = bool(home_order or away_order or home_pitcher or away_pitcher)
        if both_full:
            classification = LINEUP_OBSERVED_FULL
        elif any_data:
            classification = LINEUP_PARTIAL
        else:
            classification = LINEUP_UNAVAILABLE

        return LineupObservation(
            game_id=game_id,
            classification=classification,
            home_order=home_order,
            away_order=away_order,
            home_pitcher=home_pitcher,
            away_pitcher=away_pitcher,
            home_lineup_status=home_status,
            away_lineup_status=away_status,
            detail=game.get("status", {}).get("detailedState"),
        )

    @staticmethod
    def _normalize_order(players: object) -> tuple[int, ...]:
        if not isinstance(players, list):
            return ()
        order: list[int] = []
        for p in players:
            if isinstance(p, dict) and isinstance(p.get("id"), int):
                order.append(p["id"])
        return tuple(order)

    @staticmethod
    def _normalize_probable(team: object) -> dict | None:
        if not isinstance(team, dict):
            return None
        pp = team.get("probablePitcher") or {}
        pid = pp.get("id") if isinstance(pp, dict) else None
        if not isinstance(pid, int):
            return None
        # A probable pitcher is ALWAYS probable under the current provider.
        return {"id": pid, "epistemic_status": PITCHER_PROBABLE}

    @staticmethod
    def _side_status(order: tuple[int, ...]) -> str:
        if len(order) == _EXPECTED_LINEUP_SIZE:
            return LINEUP_OBSERVED_FULL
        if order:
            return LINEUP_PARTIAL
        return LINEUP_UNAVAILABLE
