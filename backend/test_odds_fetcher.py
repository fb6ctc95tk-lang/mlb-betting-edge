"""
Test script — odds_api_io fetcher.
Prints standardized moneyline odds records to the terminal.

NO database writes. NO FastAPI. Just a fetcher test.

How to run:
    cd backend
    python test_odds_fetcher.py
"""

import sys
from fetchers import odds_api_io

# Windows terminals default to a non-UTF-8 encoding, which can break
# accented characters in team names.
sys.stdout.reconfigure(encoding="utf-8")


def print_odds(odds_records):
    print()
    print("=" * 60)
    print("  Standardized Moneyline Odds (odds_api_io fetcher)")
    print("=" * 60)

    if not odds_records:
        print("\n  No odds records returned.")
        print("  (Some games just don't have odds posted yet — try again")
        print("   closer to game time.)\n")
        return

    for r in odds_records:
        print(f"\n  {r['away_team']} @ {r['home_team']}   {r['game_time']}")
        print(f"    Sportsbook: {r['sportsbook']}")
        print(
            f"    Away ML: {r['away_moneyline_decimal']} "
            f"({r['away_moneyline_american']:+d})"
        )
        print(
            f"    Home ML: {r['home_moneyline_decimal']} "
            f"({r['home_moneyline_american']:+d})"
        )
        print(f"    event_id: {r['event_id']}")
        print(f"    recorded_at: {r['recorded_at']}")

    print()


def main():
    print("\nFetching upcoming MLB moneyline odds...")
    odds_records = odds_api_io.get_moneyline_odds(max_games=5)
    print_odds(odds_records)

    print("=" * 60)
    print(f"  Fetcher returned {len(odds_records)} odds record(s).")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
