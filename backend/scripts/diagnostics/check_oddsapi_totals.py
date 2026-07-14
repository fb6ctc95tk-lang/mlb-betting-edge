"""
Diagnostic: OddsAPI.io Full-Game Totals Availability
=====================================================
Read-only. Does NOT write to the database, modify ingestion,
or change any production code path.

Run from the project root:
    backend/venv/Scripts/python.exe backend/scripts/diagnostics/check_oddsapi_totals.py

Purpose:
    Determine whether the existing OddsAPI.io key/plan returns
    Full-Game Totals (over/under) market data for MLB events.

    The production fetcher (backend/fetchers/odds_api_io.py) silently
    discards every market where name != "ML". This script calls the same
    endpoint without that filter and reports every market name that
    actually appears in the response. It also tests with explicit
    markets=totals and markets=ML,totals parameters to determine whether
    the totals market is valid on this account tier.

Result is used to decide whether Full-Game Totals support can be added
using the current provider, or whether it requires a plan upgrade.

Note: Run on a day when regular-season games are scheduled and
bookmakers have posted lines (typically same-day or one day prior).
Running during the All-Star break or very early before lines open will
produce empty bookmakers on all events.
"""

import os
import sys

import requests
from dotenv import load_dotenv

# Load backend/.env using an explicit path so the script works correctly
# regardless of working directory — same approach as backend/db.py.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

API_KEY = os.getenv("ODDS_API_KEY")

# These constants mirror backend/fetchers/odds_api_io.py exactly.
BASE_URL = "https://api.odds-api.io/v3"
SPORT = "baseball"
LEAGUE = "usa-mlb"
BOOKMAKERS = "Bet365,DraftKings"

# Inspect up to this many events. One is usually enough to confirm presence
# or absence of totals; three guards against games where no markets are
# posted yet.
MAX_EVENTS_TO_CHECK = 3


def main():
    print("=" * 60)
    print("OddsAPI.io Full-Game Totals Availability Diagnostic")
    print("=" * 60)
    print(f"Base URL    : {BASE_URL}")
    print(f"Sport       : {SPORT}")
    print(f"League      : {LEAGUE}")
    print(f"Bookmakers  : {BOOKMAKERS}")
    print(f"API key     : {'SET' if API_KEY and API_KEY != 'your_api_key_here' else 'MISSING'}")
    print()

    if not API_KEY or API_KEY == "your_api_key_here":
        print("ERROR: ODDS_API_KEY is not set in backend/.env.")
        print("Cannot run diagnostic without a valid API key.")
        print("See docs/ODDS_API_SETUP.md for setup instructions.")
        sys.exit(1)

    # --- Step 1: Fetch upcoming events ---
    print("Step 1: Fetching upcoming MLB events ...")
    events = _get_upcoming_events()
    print(f"  Pending events found : {len(events)}")

    if not events:
        print()
        print("RESULT: No pending MLB events found.")
        print("  Cannot determine totals availability — no events to inspect.")
        print("  Re-run on a day with upcoming games for a conclusive result.")
        return

    to_check = events[:MAX_EVENTS_TO_CHECK]
    first_date = to_check[0].get("date", "?")
    print(f"  Earliest pending event : {first_date}")
    print(f"  Will inspect           : {len(to_check)} event(s)")
    print()

    # --- Step 2: Fetch raw odds (no market filter) for each event ---
    totals_found = False
    totals_example = None
    non_ml_seen = []
    all_empty = True

    for i, event in enumerate(to_check, 1):
        event_id = event.get("id")
        matchup = f"{event.get('away', '?')} @ {event.get('home', '?')}"
        game_time = event.get("date", "unknown")
        print(f"Step 2.{i}: Raw odds for event {event_id}")
        print(f"  Matchup   : {matchup}")
        print(f"  Game time : {game_time}")

        odds_data = _get_raw_odds(event_id)
        if odds_data is None:
            print("  Skipping — request failed.")
            print()
            continue

        bookmakers = odds_data.get("bookmakers") if isinstance(odds_data, dict) else None

        if bookmakers is None:
            print("  Response has no 'bookmakers' key.")
            _describe_shape(odds_data)
            print()
            continue

        if not bookmakers:
            print("  'bookmakers' present but empty — no markets posted for this event yet.")
            print()
            continue

        all_empty = False
        for book, markets in bookmakers.items():
            if not isinstance(markets, list):
                print(f"  [{book}] Unexpected markets value type: {type(markets)}")
                continue

            names = [m.get("name", "<no name>") for m in markets]
            print(f"  [{book}] Market names in response: {names}")

            for market in markets:
                name = market.get("name", "")
                if name == "ML":
                    continue
                non_ml_seen.append({"book": book, "name": name, "event": matchup})
                print(f"    NON-ML MARKET FOUND : name={repr(name)}")
                print(f"    Full object         : {market}")
                if not totals_found:
                    totals_found = True
                    totals_example = {"book": book, "event": matchup, "market": market}

        print()

    # --- Step 3: Probe whether the 'markets' parameter is accepted ---
    # Test with markets=totals and markets=ML,totals on the first event.
    # A 200 response (even with empty bookmakers) means the parameter is
    # recognized. A 400/422 means the plan does not support this market.
    print("Step 3: Probe markets parameter support ...")
    first_event_id = to_check[0]["id"]
    first_matchup = f"{to_check[0].get('away','?')} @ {to_check[0].get('home','?')}"
    print(f"  Using event {first_event_id} ({first_matchup})")
    print()

    _probe_market_param("totals", first_event_id)
    _probe_market_param("ML,totals", first_event_id)

    # --- Step 4: Final verdict ---
    print("=" * 60)
    print("DIAGNOSTIC RESULT")
    print("=" * 60)
    print()

    if totals_found:
        print("Non-ML markets observed  : YES")
        print()
        m = totals_example["market"]
        print(f"  First non-ML market")
        print(f"  Bookmaker    : {totals_example['book']}")
        print(f"  Event        : {totals_example['event']}")
        print(f"  Market name  : {m.get('name')}")
        print(f"  Market keys  : {list(m.keys())}")
        odds_list = m.get("odds", [])
        if odds_list:
            print(f"  Odds entries : {len(odds_list)}")
            for entry in odds_list:
                print(f"    {entry}")
        else:
            print("  Odds entries : none (empty odds list)")

        if len(non_ml_seen) > 1:
            all_names = sorted({r["name"] for r in non_ml_seen})
            print()
            print(f"  All non-ML market names observed: {all_names}")

    elif all_empty:
        print("Non-ML markets observed  : INCONCLUSIVE")
        print()
        print("  All events returned empty bookmakers.")
        print("  This means no markets have been posted yet for upcoming games.")
        print()
        print("  This is expected when:")
        print("    - Running during the MLB All-Star break")
        print("    - Running very early before bookmakers post lines")
        print("    - All inspected events are 2+ days away")
        print()
        print("  This result does NOT confirm totals are unavailable.")
        print("  Re-run on a regular-season game day with active markets.")

    else:
        print("Non-ML markets observed  : NO")
        print()
        print("  Events had populated bookmakers but all markets were 'ML'.")
        print("  No totals or other market types appeared.")
        print()
        print("  Possible reasons:")
        print("    1. Free tier plan does not include totals markets")
        print("    2. Bet365/DraftKings do not offer totals via this API tier")
        print("    3. A different endpoint or parameter is needed for totals")

    print()
    print("This diagnostic is read-only.")
    print("No database writes. No production code was changed.")


def _probe_market_param(markets_value, event_id):
    """Test whether a specific markets= parameter value is accepted by the API."""
    params = {
        "apiKey": API_KEY,
        "sport": SPORT,
        "eventId": event_id,
        "bookmakers": BOOKMAKERS,
        "markets": markets_value,
    }
    try:
        response = requests.get(f"{BASE_URL}/odds", params=params, timeout=10)
        books = {}
        if response.ok:
            data = response.json()
            books = data.get("bookmakers", {}) if isinstance(data, dict) else {}
        has_markets = bool(books) and any(bool(v) for v in books.values())
        status_label = "ACCEPTED" if response.ok else f"REJECTED ({response.status_code})"
        markets_label = "markets returned" if has_markets else "empty bookmakers"
        print(f"  markets={markets_value!r:<16} HTTP {response.status_code} {status_label} — {markets_label}")
        if not response.ok:
            print(f"    Error body: {response.text[:200]}")
    except Exception as exc:
        print(f"  markets={markets_value!r:<16} Error: {exc}")


def _get_upcoming_events():
    url = f"{BASE_URL}/events"
    params = {"apiKey": API_KEY, "sport": SPORT, "league": LEAGUE}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        pending = [e for e in data if e.get("status") == "pending" and e.get("date")]
        pending.sort(key=lambda e: e["date"])
        return pending
    except requests.HTTPError as exc:
        status = exc.response.status_code
        body = exc.response.text[:300]
        print(f"  HTTP {status} fetching events: {body}")
        return []
    except Exception as exc:
        print(f"  Error fetching events: {exc}")
        return []


def _get_raw_odds(event_id):
    """Fetch odds for one event with NO market name filter applied."""
    url = f"{BASE_URL}/odds"
    params = {
        "apiKey": API_KEY,
        "sport": SPORT,
        "eventId": event_id,
        "bookmakers": BOOKMAKERS,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code
        body = exc.response.text[:300]
        print(f"  HTTP {status} fetching odds: {body}")
        return None
    except Exception as exc:
        print(f"  Error fetching odds: {exc}")
        return None


def _describe_shape(data):
    if isinstance(data, dict):
        print(f"  Response keys : {list(data.keys())}")
    elif isinstance(data, list):
        print(f"  Response is a list of {len(data)} items")
    else:
        print(f"  Response type : {type(data)}")


if __name__ == "__main__":
    main()
