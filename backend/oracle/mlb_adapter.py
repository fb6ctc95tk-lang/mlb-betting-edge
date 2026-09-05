"""Oracle Inc-1 — MLB Sport Module Adapter (N-2).

Concrete implementation of SportModuleAdapter for MLB via MLB Stats API.
Calls GET /api/v1/schedule for preliminary game data (real implementation;
authorized by PM-783/Authority B and PM-781/Authority A). No API key required.
"""

from __future__ import annotations

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
