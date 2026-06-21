from datetime import date
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def _mock_conn(fetchone_values):
    cur = MagicMock()
    cur.fetchone.side_effect = fetchone_values
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


# fetchone call order when research_date is found:
#   1. MAX(game_date)
#   2. COUNT games
#   3. COUNT odds_records
#   4. COUNT weather_records
#   5. COUNT bullpen_records
#   6. COUNT injury_records
#
# When research_date is None (no games at all):
#   1. MAX(game_date) → None
#   2. COUNT injury_records


def test_data_quality_healthy():
    conn = _mock_conn([
        (date(2026, 6, 20),),
        (14,),
        (14,),
        (14,),
        (28,),
        (87,),
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["games"] == 14
    assert body["odds_records"] == 14
    assert body["weather_records"] == 14
    assert body["bullpen_records"] == 28
    assert body["injury_records"] == 87
    assert body["research_date"] == "2026-06-20"


def test_data_quality_warning_weather_missing():
    conn = _mock_conn([
        (date(2026, 6, 20),),
        (14,),
        (14,),
        (0,),   # weather missing
        (28,),
        (0,),
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    assert res.json()["status"] == "warning"


def test_data_quality_warning_bullpen_missing():
    conn = _mock_conn([
        (date(2026, 6, 20),),
        (14,),
        (14,),
        (14,),
        (0,),   # bullpen missing
        (0,),
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    assert res.json()["status"] == "warning"


def test_data_quality_failed_no_games():
    conn = _mock_conn([
        (None,),  # no games in DB at all
        (0,),     # injury_records
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    body = res.json()
    assert body["status"] == "failed"
    assert body["games"] == 0
    assert body["research_date"] is None


def test_data_quality_failed_no_odds():
    conn = _mock_conn([
        (date(2026, 6, 20),),
        (14,),
        (0,),   # odds missing — critical failure
        (14,),
        (28,),
        (0,),
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    assert res.json()["status"] == "failed"


def test_data_quality_has_all_keys():
    conn = _mock_conn([
        (date(2026, 6, 20),),
        (14,), (14,), (14,), (28,), (87,),
    ])
    with patch("backend.routers.health.get_db_connection", return_value=conn):
        res = client.get("/health/data-quality")
    assert res.status_code == 200
    body = res.json()
    for key in ("games", "odds_records", "weather_records", "bullpen_records",
                "injury_records", "research_date", "status"):
        assert key in body, f"missing key: {key}"
