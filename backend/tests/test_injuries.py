import pytest
from unittest.mock import MagicMock, patch

import backend.fetchers.injuries as injuries_fetcher
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

KNOWN_DATE = "2026-06-18"

_MOCK_RESPONSE = {
    "injuries": [
        {
            "team": {"abbreviation": "NYY"},
            "injuries": [
                {
                    "athlete": {"fullName": "Aaron Judge"},
                    "status": "10-Day IL",
                    "longComment": "Right hip inflammation.",
                    "shortComment": "Hip",
                }
            ],
        },
        {
            "team": {"abbreviation": "BOS"},
            "injuries": [
                {
                    "athlete": {"fullName": "Rafael Devers"},
                    "status": "Day-To-Day",
                    "longComment": "",
                    "shortComment": "Wrist",
                },
                {
                    "athlete": {"fullName": "Chris Sale"},
                    "status": "15-Day IL",
                    "longComment": "Left shoulder inflammation.",
                    "shortComment": "Shoulder",
                },
            ],
        },
    ]
}


def _mock_get(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


def test_parses_player_name_and_status():
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get(_MOCK_RESPONSE)):
        result = injuries_fetcher.get_mlb_injuries()
    nyyinjuries = [r for r in result if r["team_abbreviation"] == "NYY"]
    assert len(nyyinjuries) == 1
    assert nyyinjuries[0]["player_name"] == "Aaron Judge"
    assert nyyinjuries[0]["injury_status"] == "10-Day IL"
    assert nyyinjuries[0]["injury_description"] == "Right hip inflammation."


def test_multiple_injuries_per_team():
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get(_MOCK_RESPONSE)):
        result = injuries_fetcher.get_mlb_injuries()
    bos = [r for r in result if r["team_abbreviation"] == "BOS"]
    assert len(bos) == 2


def test_falls_back_to_short_comment_when_no_long_comment():
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get(_MOCK_RESPONSE)):
        result = injuries_fetcher.get_mlb_injuries()
    devers = next(r for r in result if r["player_name"] == "Rafael Devers")
    assert devers["injury_description"] == "Wrist"


def test_empty_response_returns_empty_list():
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get({"injuries": []})):
        result = injuries_fetcher.get_mlb_injuries()
    assert result == []


def test_maps_oak_to_ath():
    data = {
        "injuries": [
            {
                "team": {"abbreviation": "OAK"},
                "injuries": [
                    {"athlete": {"fullName": "Test Player"}, "status": "DTD", "longComment": "Knee"}
                ],
            }
        ]
    }
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get(data)):
        result = injuries_fetcher.get_mlb_injuries()
    assert result[0]["team_abbreviation"] == "ATH"


def test_skips_entries_with_no_player_name():
    data = {
        "injuries": [
            {
                "team": {"abbreviation": "LAD"},
                "injuries": [
                    {"athlete": {}, "status": "IL", "longComment": "Unknown"},
                ],
            }
        ]
    }
    with patch("backend.fetchers.injuries.requests.get", return_value=_mock_get(data)):
        result = injuries_fetcher.get_mlb_injuries()
    assert result == []


def test_research_includes_injury_keys():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    assert res.status_code == 200
    games = res.json()
    if not games:
        pytest.skip("No games stored for KNOWN_DATE — run backfill first")
    assert "away_injuries" in games[0]
    assert "home_injuries" in games[0]
    assert isinstance(games[0]["away_injuries"], list)
    assert isinstance(games[0]["home_injuries"], list)
