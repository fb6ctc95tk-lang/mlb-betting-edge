"""
Fetches today's MLB games and current moneyline odds, then saves them
to the local PostgreSQL database.

Run from the repo root:
    backend/venv/Scripts/python.exe backend/scripts/save_live_data.py
"""

import os
import sys
from datetime import datetime, timedelta

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fetchers import mlb_stats_api
from fetchers import odds_api_io

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# abbreviation -> (full team name, city)
# Used to seed the teams table, since the games fetcher only gives abbreviations.
TEAM_NAMES = {
    "AZ": ("Arizona Diamondbacks", "Arizona"),
    "ATL": ("Atlanta Braves", "Atlanta"),
    "BAL": ("Baltimore Orioles", "Baltimore"),
    "BOS": ("Boston Red Sox", "Boston"),
    "CHC": ("Chicago Cubs", "Chicago"),
    "CWS": ("Chicago White Sox", "Chicago"),
    "CIN": ("Cincinnati Reds", "Cincinnati"),
    "CLE": ("Cleveland Guardians", "Cleveland"),
    "COL": ("Colorado Rockies", "Colorado"),
    "DET": ("Detroit Tigers", "Detroit"),
    "HOU": ("Houston Astros", "Houston"),
    "KC": ("Kansas City Royals", "Kansas City"),
    "LAA": ("Los Angeles Angels", "Los Angeles"),
    "LAD": ("Los Angeles Dodgers", "Los Angeles"),
    "MIA": ("Miami Marlins", "Miami"),
    "MIL": ("Milwaukee Brewers", "Milwaukee"),
    "MIN": ("Minnesota Twins", "Minnesota"),
    "NYM": ("New York Mets", "New York"),
    "NYY": ("New York Yankees", "New York"),
    "ATH": ("Athletics", "Sacramento"),
    "OAK": ("Athletics", "Oakland"),
    "PHI": ("Philadelphia Phillies", "Philadelphia"),
    "PIT": ("Pittsburgh Pirates", "Pittsburgh"),
    "SD": ("San Diego Padres", "San Diego"),
    "SF": ("San Francisco Giants", "San Francisco"),
    "SEA": ("Seattle Mariners", "Seattle"),
    "STL": ("St. Louis Cardinals", "St. Louis"),
    "TB": ("Tampa Bay Rays", "Tampa Bay"),
    "TEX": ("Texas Rangers", "Texas"),
    "TOR": ("Toronto Blue Jays", "Toronto"),
    "WSH": ("Washington Nationals", "Washington"),
}


def get_or_create_team(cur, abbreviation):
    full_name, city = TEAM_NAMES.get(abbreviation, (abbreviation, abbreviation))

    cur.execute(
        """
        INSERT INTO teams (name, abbreviation, city)
        VALUES (%s, %s, %s)
        ON CONFLICT (abbreviation) DO NOTHING
        """,
        (full_name, abbreviation, city),
    )
    cur.execute("SELECT id FROM teams WHERE abbreviation = %s", (abbreviation,))
    return cur.fetchone()[0]


def save_games(cur, games):
    """Insert or update today's games. Returns (count saved, list of saved game info)."""
    saved = 0
    saved_games = []

    for game in games:
        if not game["home_team"] or not game["away_team"]:
            continue

        home_id = get_or_create_team(cur, game["home_team"])
        away_id = get_or_create_team(cur, game["away_team"])

        cur.execute(
            """
            INSERT INTO games (
                external_game_id, game_date, game_time,
                home_team_id, away_team_id, status,
                home_score, away_score
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (external_game_id) DO UPDATE SET
                game_date = EXCLUDED.game_date,
                game_time = EXCLUDED.game_time,
                status = EXCLUDED.status,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score
            RETURNING id
            """,
            (
                game["external_game_id"], game["game_date"], game["game_time"],
                home_id, away_id, game["status"],
                game["home_score"], game["away_score"],
            ),
        )
        game_id = cur.fetchone()[0]
        saved += 1
        saved_games.append({
            "id": game_id,
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "game_date": game["game_date"],
            "home_pitcher": game["home_pitcher"],
            "away_pitcher": game["away_pitcher"],
        })

    return saved, saved_games


def save_starting_pitchers(cur, saved_games):
    """Insert or update the probable starting pitchers for each saved game."""
    saved = 0
    with_pitchers = 0

    for game in saved_games:
        cur.execute(
            """
            INSERT INTO starting_pitchers (game_id, home_pitcher, away_pitcher)
            VALUES (%s, %s, %s)
            ON CONFLICT (game_id) DO UPDATE SET
                home_pitcher = EXCLUDED.home_pitcher,
                away_pitcher = EXCLUDED.away_pitcher
            """,
            (game["id"], game["home_pitcher"], game["away_pitcher"]),
        )
        saved += 1
        if game["home_pitcher"] or game["away_pitcher"]:
            with_pitchers += 1

    return saved, with_pitchers


def save_team_records(cur, records):
    """Insert or update each team's current win/loss record."""
    saved = 0

    for record in records:
        if not record["team"]:
            continue

        team_id = get_or_create_team(cur, record["team"])

        cur.execute(
            """
            INSERT INTO team_records (
                team_id, season, wins, losses,
                home_wins, home_losses, away_wins, away_losses
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id, season) DO UPDATE SET
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                home_wins = EXCLUDED.home_wins,
                home_losses = EXCLUDED.home_losses,
                away_wins = EXCLUDED.away_wins,
                away_losses = EXCLUDED.away_losses
            """,
            (
                team_id, record["season"],
                record["wins"] or 0, record["losses"] or 0,
                record["home_wins"] or 0, record["home_losses"] or 0,
                record["away_wins"] or 0, record["away_losses"] or 0,
            ),
        )
        saved += 1

    return saved


def name_overlap_score(odds_team_name, abbreviation):
    """Count shared words (e.g. 'Yankees') between an odds team name and a saved team."""
    full_name, city = TEAM_NAMES.get(abbreviation, (abbreviation, abbreviation))

    odds_words = {w for w in odds_team_name.lower().split() if len(w) > 2}
    team_words = {w for w in (full_name + " " + city).lower().split() if len(w) > 2}

    return len(odds_words & team_words)


def find_matching_game(saved_games, odds_record):
    """Find the saved game this odds record belongs to, by team names + date.

    Returns (game, swapped) where swapped is True if the odds record's
    home/away labels are reversed compared to our saved game.
    """
    odds_date = odds_record["game_time"][:10]  # "YYYY-MM-DD"

    best_match = None
    best_score = 0

    for game in saved_games:
        # game_date is the MLB schedule date, but odds_date comes from
        # OddsAPI.io as a UTC date - night games' UTC date can be one day
        # after the schedule date, so accept either.
        game_date = datetime.strptime(game["game_date"], "%Y-%m-%d")
        next_day = (game_date + timedelta(days=1)).strftime("%Y-%m-%d")
        if odds_date not in (game["game_date"], next_day):
            continue

        score_normal = (
            name_overlap_score(odds_record["home_team"], game["home_team"])
            + name_overlap_score(odds_record["away_team"], game["away_team"])
        )
        score_swapped = (
            name_overlap_score(odds_record["home_team"], game["away_team"])
            + name_overlap_score(odds_record["away_team"], game["home_team"])
        )

        if score_normal > best_score and score_normal >= score_swapped:
            best_score = score_normal
            best_match = (game, False)
        elif score_swapped > best_score:
            best_score = score_swapped
            best_match = (game, True)

    if best_score == 0:
        return None
    return best_match


def save_odds(cur, saved_games, odds_records):
    """Insert one odds_history row per odds record that matches a saved game."""
    saved = 0
    skipped = 0

    for odds in odds_records:
        match = find_matching_game(saved_games, odds)
        if match is None:
            skipped += 1
            continue

        game, swapped = match
        if swapped:
            home_ml = odds["away_moneyline_american"]
            away_ml = odds["home_moneyline_american"]
        else:
            home_ml = odds["home_moneyline_american"]
            away_ml = odds["away_moneyline_american"]

        cur.execute(
            """
            INSERT INTO odds_history (game_id, sportsbook, home_moneyline, away_moneyline, recorded_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (game["id"], odds["sportsbook"], home_ml, away_ml, odds["recorded_at"]),
        )
        saved += 1

    return saved, skipped


def main():
    if not DATABASE_URL:
        print("FAILED: DATABASE_URL is not set in backend/.env")
        sys.exit(1)

    print("Fetching today's games from MLB Stats API...")
    games = mlb_stats_api.get_todays_games()
    print(f"  Found {len(games)} games")

    print("Fetching team records from MLB Stats API...")
    team_records = mlb_stats_api.get_team_records()
    print(f"  Found {len(team_records)} team records")

    print("Fetching moneyline odds from OddsAPI.io...")
    try:
        odds_records = odds_api_io.get_moneyline_odds()
        print(f"  Found {len(odds_records)} odds records")
    except RuntimeError as e:
        print(f"  Skipping odds: {e}")
        odds_records = []

    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"FAILED to connect to the database: {e}")
        sys.exit(1)

    cur = conn.cursor()

    games_saved, saved_games = save_games(cur, games)
    pitchers_saved, games_with_pitchers = save_starting_pitchers(cur, saved_games)
    records_saved = save_team_records(cur, team_records)
    odds_saved, odds_skipped = save_odds(cur, saved_games, odds_records)

    conn.commit()
    cur.close()
    conn.close()

    print()
    print(f"Saved {games_saved} games")
    print(f"Saved {pitchers_saved} starting pitcher rows ({games_with_pitchers} with a probable pitcher)")
    print(f"Saved {records_saved} team records")
    if odds_skipped:
        print(f"Saved {odds_saved} odds rows ({odds_skipped} skipped - no matching game today)")
    else:
        print(f"Saved {odds_saved} odds rows")


if __name__ == "__main__":
    main()
