from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..db import get_db_connection
from ..odds_math import american_odds_to_implied_probability
from ..services.team_form import get_team_last_10_form
from ..services.streak import get_team_streak

router = APIRouter()


def _get_research_for_date(conn, target_date):
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
        (target_date,),
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
        (target_date,),
    )
    odds_rows = cur.fetchall()

    cur.execute(
        """
        SELECT DISTINCT ON (team_id)
            team_id,
            wins,
            losses,
            home_wins,
            home_losses,
            away_wins,
            away_losses
        FROM team_records
        ORDER BY team_id, season DESC
        """
    )
    record_rows = cur.fetchall()

    cur.execute(
        """
        SELECT team_id, player_name, injury_status, injury_description
        FROM team_injuries
        ORDER BY team_id, player_name
        """
    )
    injury_rows = cur.fetchall()

    cur.execute(
        """
        SELECT team_id, previous_game_date, bullpen_innings_last_game, played_yesterday
        FROM team_bullpen_context
        WHERE reference_date = %s
        """,
        (target_date,),
    )
    bullpen_rows = cur.fetchall()

    cur.execute(
        """
        SELECT gw.game_id, gw.temperature, gw.wind_speed, gw.wind_direction, gw.precipitation_chance
        FROM game_weather gw
        JOIN games g ON g.id = gw.game_id
        WHERE g.game_date = %s
        """,
        (target_date,),
    )
    weather_rows = cur.fetchall()

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
        (target_date,),
    )
    movement_rows = cur.fetchall()

    cur.close()

    injuries_by_team_id: dict = {}
    for team_id, player_name, status, description in injury_rows:
        injuries_by_team_id.setdefault(team_id, []).append({
            "player_name": player_name,
            "injury_status": status,
            "injury_description": description,
        })

    bullpen_by_team_id = {
        team_id: {
            "previous_game_date": prev_date.isoformat() if prev_date else None,
            "bullpen_innings_last_game": float(innings) if innings is not None else None,
            "played_yesterday": played_yesterday,
        }
        for team_id, prev_date, innings, played_yesterday in bullpen_rows
    }

    weather_by_game = {
        game_id: {
            "temperature": float(temperature) if temperature is not None else None,
            "wind_speed": float(wind_speed) if wind_speed is not None else None,
            "wind_direction": wind_direction,
            "precipitation_chance": precipitation_chance,
        }
        for game_id, temperature, wind_speed, wind_direction, precipitation_chance in weather_rows
    }

    unique_team_ids = {row[8] for row in game_rows} | {row[9] for row in game_rows}
    form_by_team_id = {
        team_id: get_team_last_10_form(conn, team_id, target_date)
        for team_id in unique_team_ids
    }
    streak_by_team_id = {
        team_id: get_team_streak(conn, team_id, target_date)
        for team_id in unique_team_ids
    }

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
        for team_id, wins, losses, home_wins, home_losses, away_wins, away_losses in record_rows
    }

    splits_by_team_id = {
        team_id: {
            "home_wins": home_wins,
            "home_losses": home_losses,
            "home_record": f"{home_wins}-{home_losses}",
            "away_wins": away_wins,
            "away_losses": away_losses,
            "road_record": f"{away_wins}-{away_losses}",
        }
        for team_id, wins, losses, home_wins, home_losses, away_wins, away_losses in record_rows
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
            "away_team_form": form_by_team_id.get(away_team_id),
            "home_team_form": form_by_team_id.get(home_team_id),
            "away_team_streak": streak_by_team_id.get(away_team_id),
            "home_team_streak": streak_by_team_id.get(home_team_id),
            "away_team_splits": {
                "road_record": splits_by_team_id[away_team_id]["road_record"],
                "road_wins": splits_by_team_id[away_team_id]["away_wins"],
                "road_losses": splits_by_team_id[away_team_id]["away_losses"],
            } if away_team_id in splits_by_team_id else None,
            "home_team_splits": {
                "home_record": splits_by_team_id[home_team_id]["home_record"],
                "home_wins": splits_by_team_id[home_team_id]["home_wins"],
                "home_losses": splits_by_team_id[home_team_id]["home_losses"],
            } if home_team_id in splits_by_team_id else None,
            "odds": odds_by_game.get(game_id, []),
            "line_movement": movement_by_game.get(game_id, []),
            "weather": weather_by_game.get(game_id),
            "away_injuries": injuries_by_team_id.get(away_team_id, []),
            "home_injuries": injuries_by_team_id.get(home_team_id, []),
            "away_bullpen": bullpen_by_team_id.get(away_team_id),
            "home_bullpen": bullpen_by_team_id.get(home_team_id),
        })

    return games


@router.get("/today")
def get_research_today():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    target_date = datetime.now(timezone.utc).date()

    try:
        result = _get_research_for_date(conn, target_date)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()
    return result


@router.get("/available-dates")
def get_available_dates():
    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT game_date FROM games ORDER BY game_date DESC")
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()
    return {"available_dates": [row[0].isoformat() for row in rows]}


@router.get("/date/{date_str}")
def get_research_by_date(date_str: str):
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.",
        )

    try:
        conn = get_db_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")

    try:
        result = _get_research_for_date(conn, target_date)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

    conn.close()
    return result
