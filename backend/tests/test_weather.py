import pytest
from unittest.mock import MagicMock, patch

import backend.fetchers.weather as weather_fetcher
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

KNOWN_DATE = "2026-06-18"

_MOCK_RESPONSE = {
    "current": {
        "time": "2026-06-20T14:00",
        "temperature_2m": 72.5,
        "windspeed_10m": 8.3,
        "winddirection_10m": 230,
    },
    "hourly": {
        "time": ["2026-06-20T13:00", "2026-06-20T14:00", "2026-06-20T15:00"],
        "precipitation_probability": [5, 10, 20],
    },
}


def _mock_get(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


def test_get_weather_returns_all_fields():
    with patch("backend.fetchers.weather.requests.get", return_value=_mock_get(_MOCK_RESPONSE)):
        result = weather_fetcher.get_weather(40.8296, -73.9262)

    assert result["temperature"] == 72.5
    assert result["wind_speed"] == 8.3
    assert result["wind_direction"] == 230
    assert result["precipitation_chance"] == 10


def test_get_weather_matches_precip_to_current_hour():
    response = {
        "current": {"time": "2026-06-20T15:00", "temperature_2m": 68.0, "windspeed_10m": 5.0, "winddirection_10m": 180},
        "hourly": {
            "time": ["2026-06-20T14:00", "2026-06-20T15:00"],
            "precipitation_probability": [0, 35],
        },
    }
    with patch("backend.fetchers.weather.requests.get", return_value=_mock_get(response)):
        result = weather_fetcher.get_weather(40.8296, -73.9262)

    assert result["precipitation_chance"] == 35


def test_get_weather_handles_missing_precip_hour():
    response = {
        "current": {"time": "2026-06-20T20:00", "temperature_2m": 65.0, "windspeed_10m": 3.0, "winddirection_10m": 90},
        "hourly": {
            "time": ["2026-06-20T14:00", "2026-06-20T15:00"],
            "precipitation_probability": [0, 10],
        },
    }
    with patch("backend.fetchers.weather.requests.get", return_value=_mock_get(response)):
        result = weather_fetcher.get_weather(40.8296, -73.9262)

    assert result["precipitation_chance"] is None


def test_get_weather_handles_null_wind_direction():
    response = {
        "current": {"time": "2026-06-20T14:00", "temperature_2m": 70.0, "windspeed_10m": 0.0, "winddirection_10m": None},
        "hourly": {"time": [], "precipitation_probability": []},
    }
    with patch("backend.fetchers.weather.requests.get", return_value=_mock_get(response)):
        result = weather_fetcher.get_weather(40.0, -75.0)

    assert result["wind_direction"] is None


def test_stadium_coords_covers_all_30_teams():
    expected = {
        "AZ", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
        "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "ATH",
        "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSH",
    }
    missing = expected - weather_fetcher.STADIUM_COORDS.keys()
    assert not missing, f"Missing stadium coords for: {missing}"


def test_research_endpoint_includes_weather_key():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    assert res.status_code == 200
    games = res.json()
    if not games:
        pytest.skip("No games stored for KNOWN_DATE — run backfill first")
    assert "weather" in games[0]
