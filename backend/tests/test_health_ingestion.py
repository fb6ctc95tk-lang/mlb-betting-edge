import backend.routers.health as health_router
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_healthy_log(tmp_path, monkeypatch):
    log = tmp_path / "ingestion.log"
    log.write_text(
        "[2026-06-20 04:00:55] === INGESTION START ===\n"
        "Run started: 2026-06-20 04:00:56\n"
        "Saved 14 games\n"
        "[2026-06-20 04:00:58] === INGESTION END exit=0 ===\n"
    )
    monkeypatch.setattr(health_router, "LOG_PATH", log)

    res = client.get("/health/ingestion")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["last_exit_code"] == 0
    assert body["last_run_at"] == "2026-06-20 04:00:58"


def test_failed_log(tmp_path, monkeypatch):
    log = tmp_path / "ingestion.log"
    log.write_text(
        "[2026-06-20 08:00:01] === INGESTION START ===\n"
        "FAILED to connect to the database: ...\n"
        "[2026-06-20 08:00:02] === INGESTION END exit=1 ===\n"
    )
    monkeypatch.setattr(health_router, "LOG_PATH", log)

    res = client.get("/health/ingestion")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "failed"
    assert body["last_exit_code"] == 1
    assert body["last_run_at"] == "2026-06-20 08:00:02"


def test_missing_log(tmp_path, monkeypatch):
    monkeypatch.setattr(health_router, "LOG_PATH", tmp_path / "nonexistent.log")

    res = client.get("/health/ingestion")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unknown"
    assert body["last_run_at"] is None
    assert body["last_exit_code"] is None


def test_no_end_line(tmp_path, monkeypatch):
    log = tmp_path / "ingestion.log"
    log.write_text(
        "[2026-06-20 08:00:01] === INGESTION START ===\n"
        "Run started: 2026-06-20 08:00:01\n"
    )
    monkeypatch.setattr(health_router, "LOG_PATH", log)

    res = client.get("/health/ingestion")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unknown"
    assert body["last_run_at"] is None
    assert body["last_exit_code"] is None
