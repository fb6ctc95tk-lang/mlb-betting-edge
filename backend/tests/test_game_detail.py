from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

_GAME_ROW = (
    123,
    date(2026, 6, 20),
    "23:10",
    "NYY",
    "BOS",
    "scheduled",
    "Gerrit Cole",
    "Nick Pivetta",
    5,
    3,
)
_RECORD_ROWS = [(5, 45, 30), (3, 40, 35)]
_ODDS_ROWS = [("Bet365", -145, 125), ("DraftKings", -150, 130)]
_WEATHER_ROW = (72.5, 8.3, 180, 10)
_INJURY_ROWS = [(5, "Aaron Judge", "10-Day IL", "Hip")]
_BULLPEN_ROWS = [
    (5, date(2026, 6, 19), 3.1, True),
    (3, date(2026, 6, 19), 1.2, True),
]
_MOVEMENT_ROWS = [
    (
        "Bet365",
        -140, 120, datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
        -145, 125, datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc),
    ),
]


def _mock_conn(fetchone_vals, fetchall_vals):
    cur = MagicMock()
    cur.fetchone.side_effect = list(fetchone_vals)
    cur.fetchall.side_effect = list(fetchall_vals)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def _full_conn():
    return _mock_conn(
        fetchone_vals=[_GAME_ROW, _WEATHER_ROW],
        fetchall_vals=[_RECORD_ROWS, _ODDS_ROWS, _INJURY_ROWS, _BULLPEN_ROWS, _MOVEMENT_ROWS],
    )


def test_game_detail_returns_200():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    assert res.status_code == 200


def test_game_detail_not_found_returns_404():
    conn = _mock_conn(fetchone_vals=[None], fetchall_vals=[])
    with patch("backend.routers.research.get_db_connection", return_value=conn):
        res = client.get("/research/game/999")
    assert res.status_code == 404


def test_game_detail_has_required_keys():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    for key in (
        "game_id", "game_date", "game_time", "status",
        "away_team", "home_team", "away_pitcher", "home_pitcher",
        "away_record", "home_record",
        "odds", "line_movement", "weather",
        "away_injuries", "home_injuries",
        "away_bullpen", "home_bullpen",
    ):
        assert key in body, f"missing key: {key}"


def test_game_detail_teams_and_records():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    assert body["away_team"] == "NYY"
    assert body["home_team"] == "BOS"
    assert body["away_record"] == "45-30"
    assert body["home_record"] == "40-35"
    assert body["away_pitcher"] == "Gerrit Cole"
    assert body["home_pitcher"] == "Nick Pivetta"


def test_game_detail_weather_none_when_missing():
    conn = _mock_conn(
        fetchone_vals=[_GAME_ROW, None],
        fetchall_vals=[_RECORD_ROWS, _ODDS_ROWS, _INJURY_ROWS, _BULLPEN_ROWS, _MOVEMENT_ROWS],
    )
    with patch("backend.routers.research.get_db_connection", return_value=conn):
        res = client.get("/research/game/123")
    assert res.json()["weather"] is None
