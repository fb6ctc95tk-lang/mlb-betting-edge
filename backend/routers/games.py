from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection
from ..odds_math import american_odds_to_implied_probability

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


@router.get("/today-with-odds")
def get_todays_games_with_odds():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    today = datetime.now(timezone.utc).date()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                g.id,
                g.game_date,
                g.game_time,
                at.abbreviation AS away_team,
                ht.abbreviation AS home_team,
                g.status,
                sp.away_pitcher,
                sp.home_pitcher,
                g.away_team_id,
                g.home_team_id
            FROM games g
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            LEFT JOIN starting_pitchers sp ON sp.game_id = g.id
            WHERE g.game_date = %s
            ORDER BY g.id
            """,
            (today,),
        )
        game_rows = cur.fetchall()

        cur.execute(
            """
            SELECT
                o.game_id,
                o.sportsbook,
                o.away_moneyline,
                o.home_moneyline,
                o.recorded_at
            FROM (
                SELECT DISTINCT ON (game_id, sportsbook) *
                FROM odds_history
                ORDER BY game_id, sportsbook, recorded_at DESC
            ) o
            JOIN games g ON g.id = o.game_id
            WHERE g.game_date = %s
            ORDER BY o.game_id, o.sportsbook
            """,
            (today,),
        )
        odds_rows = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT ON (team_id)
                team_id,
                wins,
                losses
            FROM team_records
            ORDER BY team_id, season DESC
            """
        )
        record_rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    odds_by_game = {}
    for game_id, sportsbook, away_ml, home_ml, recorded_at in odds_rows:
        odds_by_game.setdefault(game_id, []).append({
            "sportsbook": sportsbook,
            "away_moneyline": away_ml,
            "away_implied_probability": american_odds_to_implied_probability(away_ml),
            "home_moneyline": home_ml,
            "home_implied_probability": american_odds_to_implied_probability(home_ml),
            "recorded_at": recorded_at,
        })

    record_by_team_id = {
        team_id: f"{wins}-{losses}"
        for team_id, wins, losses in record_rows
    }

    games = []
    for (
        game_id, game_date, game_time, away_team, home_team, status,
        away_pitcher, home_pitcher, away_team_id, home_team_id,
    ) in game_rows:
        games.append({
            "game_id": game_id,
            "game_date": game_date,
            "game_time": game_time,
            "away_team": away_team,
            "home_team": home_team,
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "away_record": record_by_team_id.get(away_team_id),
            "home_record": record_by_team_id.get(home_team_id),
            "status": status,
            "odds": odds_by_game.get(game_id, []),
        })

    return games
