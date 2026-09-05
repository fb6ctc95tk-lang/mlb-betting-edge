"""Oracle Inc-1 Stage 3 — Tests for gather module and MLBAdapter (T-2).

Covers:
    A. gather_preliminary_data() — retry logic and response contract
    B. MLBAdapter — MI-6, MI-5, MI-1, observe contracts
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from backend.oracle.adapter_interface import (
    AvailabilityStatus,
    PreliminaryDataRecord,
    PreliminaryDataResponse,
    SportModuleAdapter,
    UnavailabilityReason,
)
from backend.oracle.mlb_adapter import MLBAdapter
from backend.oracle.stage3_data_gather import gather_preliminary_data


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _unavailable_response() -> PreliminaryDataResponse:
    return PreliminaryDataResponse(
        record=None,
        availability=AvailabilityStatus(
            available=False,
            reason=UnavailabilityReason.DATA_SOURCE_UNREACHABLE,
        ),
    )


def _available_response(game_id: str = "746484") -> PreliminaryDataResponse:
    from datetime import datetime, timezone
    gathered_at = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
    record = PreliminaryDataRecord(
        game_id=game_id,
        data_version_id=f"DV-{game_id}-1757044800",
        gathered_at=gathered_at,
        source_system="mlb-statsapi",
        raw_payload={"game_id": game_id},
    )
    return PreliminaryDataResponse(
        record=record,
        availability=AvailabilityStatus(available=True),
    )


# ---------------------------------------------------------------------------
# A. gather_preliminary_data() — retry logic
# ---------------------------------------------------------------------------

class TestGatherPreliminaryData:
    """A — gather_preliminary_data() retry logic and contract."""

    def test_returns_success_on_first_attempt(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _available_response()
        result = gather_preliminary_data("746484", adapter)
        assert result.availability.available is True
        adapter.get_preliminary_data.assert_called_once_with("746484")

    def test_returns_immediately_on_first_success_no_further_calls(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _available_response()
        gather_preliminary_data("746484", adapter, retry_count=3)
        assert adapter.get_preliminary_data.call_count == 1

    def test_retries_on_failure_and_succeeds_on_second_attempt(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.side_effect = [
            _unavailable_response(),
            _available_response(),
        ]
        result = gather_preliminary_data("746484", adapter, retry_count=3)
        assert result.availability.available is True
        assert adapter.get_preliminary_data.call_count == 2

    def test_retries_up_to_retry_count_on_persistent_failure(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _unavailable_response()
        gather_preliminary_data("746484", adapter, retry_count=3)
        assert adapter.get_preliminary_data.call_count == 3

    def test_returns_last_unavailable_response_after_exhaustion(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _unavailable_response()
        result = gather_preliminary_data("746484", adapter, retry_count=3)
        assert result.availability.available is False

    def test_passes_game_id_to_adapter(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _available_response("999999")
        gather_preliminary_data("999999", adapter)
        adapter.get_preliminary_data.assert_called_with("999999")

    def test_retry_count_1_calls_adapter_exactly_once_on_failure(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _unavailable_response()
        gather_preliminary_data("746484", adapter, retry_count=1)
        assert adapter.get_preliminary_data.call_count == 1

    def test_returns_preliminary_data_response_type(self):
        adapter = MagicMock(spec=SportModuleAdapter)
        adapter.get_preliminary_data.return_value = _available_response()
        result = gather_preliminary_data("746484", adapter)
        assert isinstance(result, PreliminaryDataResponse)


# ---------------------------------------------------------------------------
# B. MLBAdapter — all four MI contracts
# ---------------------------------------------------------------------------

class TestMLBAdapterIsAdapter:
    """B.0 — MLBAdapter is a concrete SportModuleAdapter."""

    def test_mlb_adapter_is_sport_module_adapter_subclass(self):
        assert issubclass(MLBAdapter, SportModuleAdapter)

    def test_mlb_adapter_instance_is_sport_module_adapter(self):
        assert isinstance(MLBAdapter(), SportModuleAdapter)

    def test_mlb_adapter_is_instantiable(self):
        adapter = MLBAdapter()
        assert adapter is not None


class TestMLBAdapterMI5Availability:
    """B.1 — MI-5: get_availability()."""

    def test_get_availability_returns_available_true(self):
        assert MLBAdapter().get_availability().available is True

    def test_get_availability_reason_is_none_when_available(self):
        assert MLBAdapter().get_availability().reason is None

    def test_get_availability_returns_availability_status(self):
        result = MLBAdapter().get_availability()
        assert isinstance(result, AvailabilityStatus)


class TestMLBAdapterMI6PreliminaryData:
    """B.2 — MI-6: get_preliminary_data() — real MLB Stats API call (request-mocked)."""

    _GAME_PK = "746484"
    _FAKE_DATA = {
        "dates": [{
            "games": [{
                "gamePk": 746484,
                "gameDate": "2026-07-25T17:10:00Z",
                "status": {"detailedState": "Scheduled"},
                "teams": {
                    "home": {
                        "team": {"abbreviation": "NYY"},
                        "probablePitcher": {"fullName": "Gerrit Cole"},
                    },
                    "away": {
                        "team": {"abbreviation": "BOS"},
                        "probablePitcher": {"fullName": "Chris Sale"},
                    },
                },
            }]
        }]
    }

    def _mock_get(self, data=None, raise_on_status=None):
        mock = MagicMock()
        mock.json.return_value = data if data is not None else self._FAKE_DATA
        if raise_on_status is not None:
            mock.raise_for_status.side_effect = raise_on_status
        return mock

    def test_returns_preliminary_data_response(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert isinstance(result, PreliminaryDataResponse)

    def test_availability_is_true_on_success(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is True

    def test_record_is_not_none_on_success(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record is not None

    def test_record_game_id_matches_argument(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record.game_id == self._GAME_PK

    def test_record_data_version_id_starts_with_dv_prefix(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record.data_version_id.startswith(f"DV-{self._GAME_PK}-")

    def test_record_source_system_is_mlb_statsapi(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record.source_system == "mlb-statsapi"

    def test_record_gathered_at_is_timezone_aware(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record.gathered_at.tzinfo is not None

    def test_record_raw_payload_is_dict(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert isinstance(result.record.raw_payload, dict)

    def test_record_raw_payload_contains_external_game_id(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.record.raw_payload.get("external_game_id") == str(self._GAME_PK)

    def test_record_is_preliminary_data_record(self):
        with patch("backend.oracle.mlb_adapter.requests.get", return_value=self._mock_get()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert isinstance(result.record, PreliminaryDataRecord)

    def test_connection_error_returns_data_source_unreachable(self):
        import requests as req
        with patch("backend.oracle.mlb_adapter.requests.get",
                   side_effect=req.exceptions.ConnectionError()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is False
        assert result.availability.reason == UnavailabilityReason.DATA_SOURCE_UNREACHABLE

    def test_timeout_returns_data_source_unreachable(self):
        import requests as req
        with patch("backend.oracle.mlb_adapter.requests.get",
                   side_effect=req.exceptions.Timeout()):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is False
        assert result.availability.reason == UnavailabilityReason.DATA_SOURCE_UNREACHABLE

    def test_http_error_returns_error_response(self):
        import requests as req
        with patch("backend.oracle.mlb_adapter.requests.get",
                   return_value=self._mock_get(raise_on_status=req.exceptions.HTTPError())):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is False
        assert result.availability.reason == UnavailabilityReason.ERROR_RESPONSE

    def test_empty_dates_returns_adapter_internal_failure(self):
        with patch("backend.oracle.mlb_adapter.requests.get",
                   return_value=self._mock_get(data={"dates": []})):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is False
        assert result.availability.reason == UnavailabilityReason.ADAPTER_INTERNAL_FAILURE

    def test_empty_games_returns_adapter_internal_failure(self):
        with patch("backend.oracle.mlb_adapter.requests.get",
                   return_value=self._mock_get(data={"dates": [{"games": []}]})):
            result = MLBAdapter().get_preliminary_data(self._GAME_PK)
        assert result.availability.available is False
        assert result.availability.reason == UnavailabilityReason.ADAPTER_INTERNAL_FAILURE


class TestMLBAdapterMI1Timestamp:
    """B.3 — MI-1: get_game_start_timestamp()."""

    def test_returns_timestamp_response(self):
        from backend.oracle.adapter_interface import TimestampResponse
        result = MLBAdapter().get_game_start_timestamp("746484")
        assert isinstance(result, TimestampResponse)

    def test_availability_is_true(self):
        result = MLBAdapter().get_game_start_timestamp("746484")
        assert result.availability.available is True

    def test_timestamp_is_not_none(self):
        result = MLBAdapter().get_game_start_timestamp("746484")
        assert result.timestamp is not None

    def test_timestamp_is_timezone_aware(self):
        result = MLBAdapter().get_game_start_timestamp("746484")
        assert result.timestamp.tzinfo is not None


class TestMLBAdapterObserve:
    """B.4 — observe(): returns no-event response."""

    def test_returns_observation_response(self):
        from backend.oracle.adapter_interface import ObservationResponse
        result = MLBAdapter().observe("746484")
        assert isinstance(result, ObservationResponse)

    def test_availability_is_true(self):
        result = MLBAdapter().observe("746484")
        assert result.availability.available is True

    def test_candidate_events_is_empty(self):
        result = MLBAdapter().observe("746484")
        assert result.candidate_events == ()

    def test_finalization_status_is_no_event(self):
        from backend.oracle.adapter_interface import FinalizationStatusCode
        result = MLBAdapter().observe("746484")
        assert result.finalization_status.code == FinalizationStatusCode.NO_EVENT
