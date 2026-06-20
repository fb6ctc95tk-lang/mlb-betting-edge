import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

RESEARCH_KEYS = {
    "away_team_form",
    "home_team_form",
    "away_team_splits",
    "home_team_splits",
    "away_team_streak",
    "home_team_streak",
    "odds",
    "line_movement",
}

KNOWN_DATE = "2026-06-18"


def test_today_returns_200():
    res = client.get("/research/today")
    assert res.status_code == 200


def test_today_returns_list():
    res = client.get("/research/today")
    assert isinstance(res.json(), list)


def test_date_returns_200():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    assert res.status_code == 200


def test_date_returns_list():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    assert isinstance(res.json(), list)


def test_date_game_has_research_keys():
    res = client.get(f"/research/date/{KNOWN_DATE}")
    games = res.json()
    if not games:
        pytest.skip("No games stored for KNOWN_DATE — run backfill first")
    first = games[0]
    missing = RESEARCH_KEYS - first.keys()
    assert not missing, f"Missing keys in game response: {missing}"


def test_bad_date_returns_422():
    res = client.get("/research/date/bad-date")
    assert res.status_code == 422


def test_available_dates_returns_200():
    res = client.get("/research/available-dates")
    assert res.status_code == 200


def test_available_dates_has_key():
    res = client.get("/research/available-dates")
    assert "available_dates" in res.json()


def test_available_dates_not_routed_as_date_param():
    res = client.get("/research/available-dates")
    body = res.json()
    assert "available_dates" in body, "Route was captured by /date/{date_str}"
    assert isinstance(body["available_dates"], list)
