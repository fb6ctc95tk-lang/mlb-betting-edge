import pytest
from unittest.mock import MagicMock, patch

import backend.fetchers.mlb_stats_api as mlb_api
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

KNOWN_DATE = "2026-06-18"

_MOCK_BOXSCORE = {
    "teams": {
        "home": {
            "pitchers": [111, 222, 333],
            "players": {
                "ID111": {"stats": {"pitching": {"inningsPitched": "6.0"}}},
                "ID222": {"stats": {"pitching": {"inningsPitched": "1.0"}}},
                "ID333": {"stats": {"pitching": {"inningsPitched": "2.0"}}},
            },
        },
        "away": {
            "pitchers": [444, 555],
            "players": {
                "ID444": {"stats": {"pitching": {"inningsPitched": "5.1"}}},
                "ID555": {"stats": {"pitching": {"inningsPitched": "3.2"}}},
            },
        },
    }
}


def _mock_get(data):
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


def test_bullpen_innings_home():
    # Home bullpen = pitchers 222 + 333 = 1.0 + 2.0 = 9 outs = 3.0 IP
    with patch("backend.fetchers.mlb_stats_api.requests.get", return_value=_mock_get(_MOCK_BOXSCORE)):
        result = mlb_api.get_bullpen_innings("748532", "home")
    assert result == 3.0


def test_bullpen_innings_away():
    # Away bullpen = pitcher 555 = 3.2 IP (3 innings + 2 outs = 11 outs)
    with patch("backend.fetchers.mlb_stats_api.requests.get", return_value=_mock_get(_MOCK_BOXSCORE)):
        result = mlb_api.get_bullpen_innings("748532", "away")
    assert result == 3.2


def test_bullpen_innings_complete_game():
    # Only 1 pitcher (complete game) — bullpen is 0.0
    boxscore = {
        "teams": {
            "home": {
                "pitchers": [111],
                "players": {"ID111": {"stats": {"pitching": {"inningsPitched": "9.0"}}}},
            }
        }
    }
    with patch("backend.fetchers.mlb_stats_api.requests.get", return_value=_mock_get(boxscore)):
        result = mlb_api.get_bullpen_innings("748532", "home")
    assert result == 0.0


def test_bullpen_innings_no_pitchers():
    boxscore = {"teams": {"home": {"pitchers": [], "players": {}}}}
    with patch("backend.fetchers.mlb_stats_api.requests.get", return_value=_mock_get(boxscore)):
        result = mlb_api.get_bullpen_innings("748532", "home")
    assert result == 0.0


def test_ip_to_outs():
    assert mlb_api._ip_to_outs("0.0") == 0
    assert mlb_api._ip_to_outs("6.0") == 18
    assert mlb_api._ip_to_outs("6.1") == 19
    assert mlb_api._ip_to_outs("6.2") == 20
    assert mlb_api._ip_to_outs("9.0") == 27


def test_outs_to_ip():
    assert mlb_api._outs_to_ip(0) == 0.0
    assert mlb_api._outs_to_ip(18) == 6.0
    assert mlb_api._outs_to_ip(19) == 6.1
    assert mlb_api._outs_to_ip(20) == 6.2
    assert mlb_api._outs_to_ip(27) == 9.0


def test_research_includes_bullpen_keys():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    assert res.status_code == 200
    games = res.json()
    if not games:
        pytest.skip("No games stored for KNOWN_DATE — run backfill first")
    assert "away_bullpen" in games[0]
    assert "home_bullpen" in games[0]
