from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection
from ..odds_math import american_odds_to_implied_probability

router = APIRouter()


@router.get("/today")
def get_research_today():
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
                o.home_moneyline
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
                op.home_moneyline  AS opening_home_ml,
                op.away_moneyline  AS opening_away_ml,
                op.recorded_at     AS opening_ts,
                la.home_moneyline  AS latest_home_ml,
                la.away_moneyline  AS latest_away_ml,
                la.recorded_at     AS latest_ts
            FROM opening op
            JOIN latest la ON la.game_id = op.game_id AND la.sportsbook = op.sportsbook
            JOIN games g   ON g.id  = op.game_id
            JOIN teams ht  ON ht.id = g.home_team_id
            JOIN teams at  ON at.id = g.away_team_id
            WHERE g.game_date = %s
            ORDER BY op.game_id, op.sportsbook
            """,
            (today,),
        )
        movement_rows = cur.fetchall()

        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()

    odds_by_game = {}
    for game_id, sportsbook, away_ml, home_ml in odds_rows:
        odds_by_game.setdefault(game_id, []).append({
            "sportsbook": sportsbook,
            "away_moneyline": away_ml,
            "away_implied_probability": american_odds_to_implied_probability(away_ml),
            "home_moneyline": home_ml,
            "home_implied_probability": american_odds_to_implied_probability(home_ml),
        })

    record_by_team_id = {
        team_id: f"{wins}-{losses}"
        for team_id, wins, losses in record_rows
    }

    movement_by_game = {}
    for (
        game_id, sportsbook, home_team, away_team,
        opening_home_ml, opening_away_ml, opening_ts,
        latest_home_ml, latest_away_ml, latest_ts,
    ) in movement_rows:
        entries = movement_by_game.setdefault(game_id, [])
        entries.append({
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
        entries.append({
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

    games = []
    for (
        game_id, game_date, game_time, away_team, home_team, status,
        away_pitcher, home_pitcher, away_team_id, home_team_id,
    ) in game_rows:
        games.append({
            "game_id": game_id,
            "game_date": game_date,
            "game_time": game_time,
            "status": status,
            "away_team": away_team,
            "home_team": home_team,
            "away_record": record_by_team_id.get(away_team_id),
            "home_record": record_by_team_id.get(home_team_id),
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "odds": odds_by_game.get(game_id, []),
            "line_movement": movement_by_game.get(game_id, []),
        })

    return games
