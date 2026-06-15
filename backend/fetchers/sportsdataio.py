"""
SportsDataIO fetcher — PAUSED.

Not used right now. We're building on the free MLB Stats API first
(see fetchers/mlb_stats_api.py). This file is kept ready for later,
most likely to add odds data (which the free API doesn't provide).

Requires SPORTSDATAIO_API_KEY in backend/.env to run.
See SETUP_GUIDE.md for how to get a key.

STANDARD SHAPE
--------------
get_todays_games() returns the SAME shape as
fetchers/mlb_stats_api.get_todays_games(). That matching shape is
the whole point — it's what lets us swap providers, or use both
side by side, without changing any code outside this folder.
"""

import os
from datetime import date
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SPORTSDATAIO_API_KEY")
BASE_URL = "https://api.sportsdata.io/v3/mlb/scores/json"

STATUS_MAP = {
    "Scheduled": "scheduled",
    "InProgress": "in_progress",
    "Final": "final",
    "F/PPD": "postponed",
    "Postponed": "postponed",
    "Suspended": "postponed",
}


def get_todays_games(target_date=None):
    """Fetch games (with probable pitchers) for a given date (default: today)."""
    if not API_KEY or API_KEY == "your_api_key_here":
        raise RuntimeError(
            "SPORTSDATAIO_API_KEY not set in backend/.env. "
            "See SETUP_GUIDE.md for how to get a key."
        )

    if target_date is None:
        target_date = date.today().strftime("%Y-%b-%d").upper()  # e.g. 2026-JUN-10

    url = f"{BASE_URL}/GamesByDate/{target_date}"
    response = requests.get(url, params={"key": API_KEY}, timeout=10)
    response.raise_for_status()

    return [_normalize_game(game) for game in response.json()]


def _normalize_game(game):
    game_datetime = game.get("DateTime", "")
    if "T" in game_datetime:
        game_date, time_part = game_datetime.split("T")
        game_time = time_part[:5]
    else:
        game_date, game_time = None, None

    return {
        "external_game_id": str(game.get("GameID")),
        "game_date": game_date,
        "game_time": game_time,
        "status": STATUS_MAP.get(game.get("Status"), "scheduled"),
        "home_team": game.get("HomeTeam"),
        "away_team": game.get("AwayTeam"),
        "home_score": game.get("HomeTeamRuns"),
        "away_score": game.get("AwayTeamRuns"),
        "home_pitcher": game.get("HomeProbablePitcher"),
        "away_pitcher": game.get("AwayProbablePitcher"),
    }
