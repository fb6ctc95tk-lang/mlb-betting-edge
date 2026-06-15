from fastapi import APIRouter, HTTPException

from ..db import get_db_connection

router = APIRouter()


@router.get("")
def get_teams():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM teams ORDER BY name")
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    return [{"team_id": row[0], "team_name": row[1]} for row in rows]
