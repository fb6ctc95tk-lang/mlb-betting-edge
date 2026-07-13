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
# team_id, wins, losses, home_wins, home_losses, away_wins, away_losses
_RECORD_ROWS = [
    (5, 45, 30, 25, 15, 20, 15),
    (3, 40, 35, 22, 18, 18, 17),
]
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

# get_team_last_10_form rows: (home_team_id, away_team_id, home_score, away_score)
# Away team (team_id=5): 2 wins — games where team_id=5 is home and wins
_AWAY_FORM_ROWS = [
    (5, 3, 5, 2),   # team 5 home, won
    (5, 3, 4, 1),   # team 5 home, won
    (5, 3, 1, 3),   # team 5 home, lost
]
# Home team (team_id=3): 1 win — games where team_id=3 is home
_HOME_FORM_ROWS = [
    (3, 5, 4, 2),   # team 3 home, won
    (3, 5, 1, 3),   # team 3 home, lost
]

# get_team_streak rows: same shape, most-recent-first
# Away team (team_id=5): W2 streak (2 consecutive wins before a loss)
_AWAY_STREAK_ROWS = [
    (5, 3, 5, 2),
    (5, 3, 4, 1),
    (5, 3, 1, 3),
]
# Home team (team_id=3): W1 streak
_HOME_STREAK_ROWS = [
    (3, 5, 4, 2),
    (3, 5, 1, 3),
]


def _mock_conn(fetchone_vals, fetchall_vals):
    cur = MagicMock()
    cur.fetchone.side_effect = list(fetchone_vals)
    cur.fetchall.side_effect = list(fetchall_vals)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def _full_conn():
    # fetchall order matches _get_research_for_game call sequence:
    # records, odds, injuries, bullpen, movement,
    # then get_team_last_10_form(away), get_team_last_10_form(home),
    # then get_team_streak(away), get_team_streak(home)
    return _mock_conn(
        fetchone_vals=[_GAME_ROW, _WEATHER_ROW],
        fetchall_vals=[
            _RECORD_ROWS, _ODDS_ROWS, _INJURY_ROWS, _BULLPEN_ROWS, _MOVEMENT_ROWS,
            _AWAY_FORM_ROWS, _HOME_FORM_ROWS,
            _AWAY_STREAK_ROWS, _HOME_STREAK_ROWS,
        ],
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
        "away_team_form", "home_team_form",
        "away_team_streak", "home_team_streak",
        "away_team_splits", "home_team_splits",
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
        fetchall_vals=[
            _RECORD_ROWS, _ODDS_ROWS, _INJURY_ROWS, _BULLPEN_ROWS, _MOVEMENT_ROWS,
            _AWAY_FORM_ROWS, _HOME_FORM_ROWS,
            _AWAY_STREAK_ROWS, _HOME_STREAK_ROWS,
        ],
    )
    with patch("backend.routers.research.get_db_connection", return_value=conn):
        res = client.get("/research/game/123")
    assert res.json()["weather"] is None


def test_game_detail_form_has_expected_shape():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    for side in ("away_team_form", "home_team_form"):
        form = body[side]
        assert form is not None, f"{side} should not be None when game rows exist"
        for field in ("last_10_games_count", "last_10_wins", "last_10_losses",
                      "last_10_record", "last_10_run_diff"):
            assert field in form, f"{side} missing field: {field}"


def test_game_detail_form_values_match_mock_rows():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    # _AWAY_FORM_ROWS: 3 games, 2 wins, 1 loss for team_id=5
    away_form = body["away_team_form"]
    assert away_form["last_10_games_count"] == 3
    assert away_form["last_10_wins"] == 2
    assert away_form["last_10_losses"] == 1
    assert away_form["last_10_record"] == "2-1"
    # _HOME_FORM_ROWS: 2 games, 1 win, 1 loss for team_id=3
    home_form = body["home_team_form"]
    assert home_form["last_10_games_count"] == 2
    assert home_form["last_10_wins"] == 1
    assert home_form["last_10_losses"] == 1


def test_game_detail_streak_has_expected_shape():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    for side in ("away_team_streak", "home_team_streak"):
        streak = body[side]
        assert streak is not None, f"{side} should not be None"
        for field in ("streak_type", "streak_count", "streak_label"):
            assert field in streak, f"{side} missing field: {field}"


def test_game_detail_streak_values_match_mock_rows():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    # _AWAY_STREAK_ROWS: W2 (2 wins then a loss) for team_id=5
    assert body["away_team_streak"]["streak_type"] == "W"
    assert body["away_team_streak"]["streak_count"] == 2
    assert body["away_team_streak"]["streak_label"] == "W2"
    # _HOME_STREAK_ROWS: W1 (1 win then a loss) for team_id=3
    assert body["home_team_streak"]["streak_type"] == "W"
    assert body["home_team_streak"]["streak_count"] == 1
    assert body["home_team_streak"]["streak_label"] == "W1"


def test_game_detail_splits_has_expected_shape():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    away_splits = body["away_team_splits"]
    assert away_splits is not None
    assert "road_record" in away_splits
    assert "road_wins" in away_splits
    assert "road_losses" in away_splits
    home_splits = body["home_team_splits"]
    assert home_splits is not None
    assert "home_record" in home_splits
    assert "home_wins" in home_splits
    assert "home_losses" in home_splits


def test_game_detail_splits_values_match_mock_rows():
    with patch("backend.routers.research.get_db_connection", return_value=_full_conn()):
        res = client.get("/research/game/123")
    body = res.json()
    # _RECORD_ROWS: team_id=5 has away_wins=20, away_losses=15
    assert body["away_team_splits"]["road_record"] == "20-15"
    assert body["away_team_splits"]["road_wins"] == 20
    assert body["away_team_splits"]["road_losses"] == 15
    # _RECORD_ROWS: team_id=3 has home_wins=22, home_losses=18
    assert body["home_team_splits"]["home_record"] == "22-18"
    assert body["home_team_splits"]["home_wins"] == 22
    assert body["home_team_splits"]["home_losses"] == 18
