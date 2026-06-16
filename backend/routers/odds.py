from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection

router = APIRouter()


@router.get("/latest")
def get_latest_odds():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                o.game_id,
                o.sportsbook,
                ht.abbreviation AS home_team,
                at.abbreviation AS away_team,
                o.home_moneyline,
                o.away_moneyline,
                o.recorded_at
            FROM (
                SELECT DISTINCT ON (game_id, sportsbook) *
                FROM odds_history
                ORDER BY game_id, sportsbook, recorded_at DESC
            ) o
            JOIN games g ON g.id = o.game_id
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            ORDER BY o.game_id, o.sportsbook
            """
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    odds = []
    for game_id, sportsbook, home_team, away_team, home_ml, away_ml, recorded_at in rows:
        odds.append({
            "game_id": game_id,
            "sportsbook": sportsbook,
            "team": home_team,
            "moneyline": home_ml,
            "last_updated": recorded_at,
        })
        odds.append({
            "game_id": game_id,
            "sportsbook": sportsbook,
            "team": away_team,
            "moneyline": away_ml,
            "last_updated": recorded_at,
        })

    return odds


@router.get("/movement")
def get_odds_movement():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute(
            """
            WITH opening AS (
                SELECT DISTINCT ON (game_id, sportsbook) *
                FROM odds_history
                ORDER BY game_id, sportsbook, recorded_at ASC
            ),
            latest AS (
                SELECT DISTINCT ON (game_id, sportsbook) *
                FROM odds_history
                ORDER BY game_id, sportsbook, recorded_at DESC
            )
            SELECT
                op.game_id,
                op.sportsbook,
                ht.abbreviation AS home_team,
                at.abbreviation AS away_team,
                op.home_moneyline  AS opening_home_moneyline,
                op.away_moneyline  AS opening_away_moneyline,
                op.recorded_at     AS opening_timestamp,
                la.home_moneyline  AS latest_home_moneyline,
                la.away_moneyline  AS latest_away_moneyline,
                la.recorded_at     AS latest_timestamp
            FROM opening op
            JOIN latest la ON la.game_id = op.game_id AND la.sportsbook = op.sportsbook
            JOIN games g   ON g.id  = op.game_id
            JOIN teams ht  ON ht.id = g.home_team_id
            JOIN teams at  ON at.id = g.away_team_id
            ORDER BY op.game_id, op.sportsbook
            """
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    movement = []
    for (
        game_id, sportsbook, home_team, away_team,
        opening_home_ml, opening_away_ml, opening_ts,
        latest_home_ml, latest_away_ml, latest_ts,
    ) in rows:
        movement.append({
            "game_id": game_id,
            "sportsbook": sportsbook,
            "team": home_team,
            "side": "home",
            "opening_moneyline": opening_home_ml,
            "latest_moneyline": latest_home_ml,
            "movement": latest_home_ml - opening_home_ml,
            "opening_timestamp": opening_ts,
            "latest_timestamp": latest_ts,
        })
        movement.append({
            "game_id": game_id,
            "sportsbook": sportsbook,
            "team": away_team,
            "side": "away",
            "opening_moneyline": opening_away_ml,
            "latest_moneyline": latest_away_ml,
            "movement": latest_away_ml - opening_away_ml,
            "opening_timestamp": opening_ts,
            "latest_timestamp": latest_ts,
        })

    return movement


@router.get("/today")
def get_todays_odds():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                o.game_id,
                g.game_date,
                g.game_time,
                o.sportsbook,
                at.abbreviation AS away_team,
                ht.abbreviation AS home_team,
                o.away_moneyline,
                o.home_moneyline,
                o.recorded_at
            FROM (
                SELECT DISTINCT ON (game_id, sportsbook) *
                FROM odds_history
                ORDER BY game_id, sportsbook, recorded_at DESC
            ) o
            JOIN games g ON g.id = o.game_id
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            WHERE g.game_date = %s
            ORDER BY o.game_id, o.sportsbook
            """,
            (datetime.now(timezone.utc).date(),),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    odds = []
    for row in rows:
        odds.append({
            "game_id": row[0],
            "game_date": row[1],
            "game_time": row[2],
            "sportsbook": row[3],
            "away_team": row[4],
            "home_team": row[5],
            "away_moneyline": row[6],
            "home_moneyline": row[7],
            "recorded_at": row[8],
        })

    return odds
