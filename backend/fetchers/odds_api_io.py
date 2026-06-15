"""
OddsAPI.io fetcher — ACTIVE, used for MLB moneyline odds.

Requires ODDS_API_KEY in backend/.env to run.
See docs/ODDS_API_SETUP.md for how to get a key.

STANDARD SHAPE
--------------
get_moneyline_odds() returns a list of odds_record dicts:

odds_record = {
    "event_id":                str,    (OddsAPI.io's own ID for the game)
    "home_team":               str,
    "away_team":               str,
    "game_time":               "YYYY-MM-DDTHH:MM:SSZ" (UTC),
    "sportsbook":               str,
    "home_moneyline_decimal":  float,
    "away_moneyline_decimal":  float,
    "home_moneyline_american": int,
    "away_moneyline_american": int,
    "recorded_at":             "YYYY-MM-DDTHH:MM:SSZ" (UTC, when this fetch ran),
}

One game can produce multiple odds_records — one per sportsbook.

Note: "event_id" is OddsAPI.io's own ID, separate from the
"external_game_id" used by fetchers/mlb_stats_api.py. Matching games
across providers (by team names + date) is a problem for a later step.
"""

import os
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.odds-api.io/v3"

# OddsAPI.io groups everything under one big sport called "baseball".
# MLB is a *league* inside that sport, with the slug "usa-mlb".
SPORT = "baseball"
LEAGUE = "usa-mlb"

# Free tier accounts are locked to exactly 2 sportsbooks, set on first use.
# This project's key is locked to Bet365 and DraftKings.
BOOKMAKERS = "Bet365,DraftKings"


def get_moneyline_odds(max_games=10):
    """Fetch moneyline odds for the next `max_games` upcoming MLB games."""
    if not API_KEY or API_KEY == "your_api_key_here":
        raise RuntimeError(
            "ODDS_API_KEY not set in backend/.env. "
            "See docs/ODDS_API_SETUP.md for how to get a key."
        )

    events = _get_upcoming_events()

    odds_records = []
    for event in events[:max_games]:
        odds_data = _get_odds_for_event(event["id"])
        odds_records.extend(_normalize_odds(event, odds_data))

    return odds_records


def _get_upcoming_events():
    url = f"{BASE_URL}/events"
    params = {"apiKey": API_KEY, "sport": SPORT, "league": LEAGUE}

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    # Only games that haven't started yet have odds worth checking.
    pending = [e for e in data if e.get("status") == "pending" and e.get("date")]
    pending.sort(key=lambda e: e["date"])
    return pending


def _get_odds_for_event(event_id):
    url = f"{BASE_URL}/odds"
    params = {
        "apiKey": API_KEY,
        "sport": SPORT,
        "eventId": event_id,
        "bookmakers": BOOKMAKERS,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _normalize_odds(event, odds_data):
    # "bookmakers" is a dict keyed by sportsbook name, e.g.
    # {"Bet365": [ {"name": "ML", "odds": [...]}, ... ], "DraftKings": [...]}
    bookmakers = odds_data.get("bookmakers") if isinstance(odds_data, dict) else None
    if not bookmakers:
        return []

    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = []

    for sportsbook, markets in bookmakers.items():
        for market in markets:
            if market.get("name") != "ML":
                continue

            for line in market.get("odds", []):
                home_dec = line.get("home")
                away_dec = line.get("away")
                if home_dec is None or away_dec is None:
                    continue

                records.append({
                    "event_id": str(event.get("id")),
                    "home_team": event.get("home"),
                    "away_team": event.get("away"),
                    "game_time": event.get("date"),
                    "sportsbook": sportsbook,
                    "home_moneyline_decimal": float(home_dec),
                    "away_moneyline_decimal": float(away_dec),
                    "home_moneyline_american": decimal_to_american(home_dec),
                    "away_moneyline_american": decimal_to_american(away_dec),
                    "recorded_at": recorded_at,
                })

    return records


def decimal_to_american(decimal_odds):
    """Convert decimal odds (e.g. 2.10) to American odds (e.g. 110) as an int."""
    decimal_odds = float(decimal_odds)
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    else:
        return round(-100 / (decimal_odds - 1))
