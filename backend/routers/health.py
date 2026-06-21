import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection

router = APIRouter()

LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "ingestion.log"
_END_LINE = re.compile(r"\[(.+?)\] === INGESTION END exit=(\d+) ===")


@router.get("/ingestion")
def ingestion_health():
    if not LOG_PATH.exists():
        return {"last_run_at": None, "last_exit_code": None, "status": "unknown"}

    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()

    for line in reversed(lines):
        m = _END_LINE.search(line)
        if m:
            exit_code = int(m.group(2))
            return {
                "last_run_at": m.group(1),
                "last_exit_code": exit_code,
                "status": "healthy" if exit_code == 0 else "failed",
            }

    return {"last_run_at": None, "last_exit_code": None, "status": "unknown"}


@router.get("/data-quality")
def data_quality():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()

        cur.execute("SELECT MAX(game_date) FROM games")
        row = cur.fetchone()
        research_date = row[0].isoformat() if row[0] else None

        if research_date:
            cur.execute("SELECT COUNT(*) FROM games WHERE game_date = %s", (research_date,))
            games = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(DISTINCT oh.game_id)
                FROM odds_history oh
                JOIN games g ON g.id = oh.game_id
                WHERE g.game_date = %s
                """,
                (research_date,),
            )
            odds_records = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM game_weather gw
                JOIN games g ON g.id = gw.game_id
                WHERE g.game_date = %s
                """,
                (research_date,),
            )
            weather_records = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM team_bullpen_context WHERE reference_date = %s",
                (research_date,),
            )
            bullpen_records = cur.fetchone()[0]
        else:
            games = odds_records = weather_records = bullpen_records = 0

        cur.execute("SELECT COUNT(*) FROM team_injuries")
        injury_records = cur.fetchone()[0]

        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    if games == 0 or odds_records == 0:
        status = "failed"
    elif weather_records == 0 or bullpen_records == 0:
        status = "warning"
    else:
        status = "healthy"

    return {
        "games": games,
        "odds_records": odds_records,
        "weather_records": weather_records,
        "bullpen_records": bullpen_records,
        "injury_records": injury_records,
        "research_date": research_date,
        "status": status,
    }
