"""
Test script — OddsAPI.io connection check.
Fetches MLB moneyline odds and prints them to the terminal.

NO database writes. NO FastAPI. Just a connection test.

How to run:
    cd backend
    python test_odds_api.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

# Windows terminals default to a non-UTF-8 encoding, which can break
# accented characters in team/player names.
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.odds-api.io/v3"

# OddsAPI.io groups everything under one big sport called "baseball".
# MLB is a *league* inside that sport, with the slug "usa-mlb".
# ("mlb" by itself is not a valid sport on this API.)
SPORT = "baseball"
LEAGUE = "usa-mlb"

# Free tier accounts are locked to exactly 2 sportsbooks. The first time
# you request odds, OddsAPI.io remembers which 2 books you asked for and
# rejects any others after that (there's a "clear selection" endpoint to
# change them, but we don't need it). This project is locked to:
BOOKMAKERS = "Bet365,DraftKings"

# Free tier = 100 requests/hour. One /odds call = 1 game's worth of odds,
# so we only check a few games to stay well under that limit.
MAX_GAMES_TO_CHECK = 5


def check_api_key():
    if not API_KEY or API_KEY == "your_api_key_here":
        print("\n ERROR: API key not set.")
        print(" Open backend/.env and set ODDS_API_KEY to your real key.")
        print(" See docs/ODDS_API_SETUP.md for instructions.\n")
        sys.exit(1)


def decimal_to_american(decimal_odds):
    """Convert decimal odds (e.g. 2.10) to American odds (e.g. +110)."""
    decimal_odds = float(decimal_odds)
    if decimal_odds >= 2.0:
        american = (decimal_odds - 1) * 100
        return f"+{round(american)}"
    else:
        american = -100 / (decimal_odds - 1)
        return f"{round(american)}"


def get_upcoming_mlb_events():
    url = f"{BASE_URL}/events"
    params = {"apiKey": API_KEY, "sport": SPORT, "league": LEAGUE}

    print(f" Calling: {url}?sport={SPORT}&league={LEAGUE}")
    response = requests.get(url, params=params, timeout=10)

    if response.status_code == 401:
        print("\n ERROR: API key was rejected (401 Unauthorized).")
        print(" Double-check your ODDS_API_KEY in backend/.env\n")
        sys.exit(1)

    if response.status_code == 429:
        print("\n ERROR: Rate limit hit (429 Too Many Requests).")
        print(" Free tier = 100 requests/hour. Wait a bit and try again.\n")
        sys.exit(1)

    response.raise_for_status()
    data = response.json()

    # Only games that haven't started yet have odds worth checking.
    pending = [e for e in data if e.get("status") == "pending" and e.get("date")]
    pending.sort(key=lambda e: e["date"])
    return pending


def get_odds_for_event(event_id):
    url = f"{BASE_URL}/odds"
    params = {
        "apiKey": API_KEY,
        "sport": SPORT,
        "eventId": event_id,
        "bookmakers": BOOKMAKERS,
    }

    response = requests.get(url, params=params, timeout=10)

    if response.status_code == 403:
        print("\n ERROR: This API key is locked to different bookmakers.")
        print(f" Tried: {BOOKMAKERS}")
        print(" Response:", response.json())
        sys.exit(1)

    response.raise_for_status()
    return response.json()


def print_moneylines(event, odds_data):
    home = event.get("home", "???")
    away = event.get("away", "???")

    print(f"\n  {away} @ {home}  ({event.get('date', '?')})")
    print("  " + "-" * 56)

    # "bookmakers" is a dict keyed by sportsbook name, e.g.
    # {"Bet365": [ {"name": "ML", "odds": [...]}, ... ], "DraftKings": [...]}
    bookmakers = odds_data.get("bookmakers") if isinstance(odds_data, dict) else None
    if not bookmakers:
        print("  No odds posted yet for this game.")
        return False

    found_moneyline = False

    for book_name, markets in bookmakers.items():
        for market in markets:
            if market.get("name") != "ML":
                continue

            for line in market.get("odds", []):
                home_dec = line.get("home")
                away_dec = line.get("away")
                if home_dec is None or away_dec is None:
                    continue

                found_moneyline = True
                home_us = decimal_to_american(home_dec)
                away_us = decimal_to_american(away_dec)

                print(
                    f"  {book_name:<12} "
                    f"{away}: {away_dec} ({away_us})    "
                    f"{home}: {home_dec} ({home_us})"
                )

    if not found_moneyline:
        print("  No 'ML' (moneyline) market found yet for this game.")

    return found_moneyline


def main():
    print("\n MLB Betting Edge — Testing OddsAPI.io connection...\n")
    check_api_key()

    events = get_upcoming_mlb_events()

    print()
    print("=" * 60)
    print("  OddsAPI.io — MLB Moneyline Odds")
    print("=" * 60)

    if not events:
        print("\n  No upcoming MLB events returned.")
        return

    print(f"\n  Found {len(events)} upcoming MLB game(s).")
    print(f"  Checking the next {min(MAX_GAMES_TO_CHECK, len(events))} for odds:")

    games_with_odds = 0
    for event in events[:MAX_GAMES_TO_CHECK]:
        odds_data = get_odds_for_event(event["id"])
        if print_moneylines(event, odds_data):
            games_with_odds += 1

    print()
    print("=" * 60)
    if games_with_odds:
        print(f"  Connection successful! Found odds for {games_with_odds} game(s).")
    else:
        print("  Connection successful, but no odds were posted yet.")
        print("  Try running this again closer to game time.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
