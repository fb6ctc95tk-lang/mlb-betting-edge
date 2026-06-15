from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection

router = APIRouter()


@router.get("/today")
def get_todays_games():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                g.id,
                g.game_date,
                g.game_time,
                ht.abbreviation AS home_team,
                at.abbreviation AS away_team,
                g.status,
                g.home_score,
                g.away_score,
                sp.home_pitcher,
                sp.away_pitcher
            FROM games g
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            LEFT JOIN starting_pitchers sp ON sp.game_id = g.id
            WHERE g.game_date = %s
            ORDER BY g.id
            """,
            (datetime.now(timezone.utc).date(),),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    games = []
    for row in rows:
        games.append({
            "game_id": row[0],
            "game_date": row[1],
            "game_time": row[2],
            "home_team": row[3],
            "away_team": row[4],
            "status": row[5],
            "home_score": row[6],
            "away_score": row[7],
            "probable_home_pitcher": row[8],
            "probable_away_pitcher": row[9],
        })

    return games
