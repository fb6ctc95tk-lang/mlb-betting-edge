"""
Test script — Free MLB Stats API connection check.
NO API KEY REQUIRED. This is the official, free MLB data source.

Fetches:
- Today's games, with starting pitchers
- Current team standings (win/loss records)

How to run:
    cd backend
    python test_mlb_stats_api.py
"""

import sys
from fetchers import mlb_stats_api

# Windows terminals default to a non-UTF-8 encoding, which breaks
# player names with accents (e.g. "Rodón"). Force UTF-8 output.
sys.stdout.reconfigure(encoding="utf-8")


def print_games(games):
    print()
    print("=" * 60)
    print("  Today's MLB Games  (MLB Stats API — free, no key needed)")
    print("=" * 60)

    if not games:
        print("\n  No games scheduled today.")
        print("  (This is normal on off days.)\n")
        return

    for i, game in enumerate(games, start=1):
        away = game["away_team"] or "???"
        home = game["home_team"] or "???"
        time = game["game_time"] or "TBD"
        status = game["status"]

        away_pitcher = game["away_pitcher"] or "TBD"
        home_pitcher = game["home_pitcher"] or "TBD"

        print(f"\n  {i}. {away} @ {home}   {time} UTC   [{status}]")
        print(f"     Pitchers: {away_pitcher}  vs  {home_pitcher}")

    print()


def print_records(records):
    print("=" * 60)
    print("  Team Records (first 5 shown)")
    print("=" * 60)

    for r in records[:5]:
        print(
            f"  {r['team']:<4} {r['wins']:>3}-{r['losses']:<3}"
            f"   Home: {r['home_wins']}-{r['home_losses']}"
            f"   Away: {r['away_wins']}-{r['away_losses']}"
        )

    remaining = len(records) - 5
    if remaining > 0:
        print(f"  ... and {remaining} more teams")

    print()


def main():
    print("\nFetching today's games...")
    games = mlb_stats_api.get_todays_games()
    print_games(games)

    print("Fetching team records...")
    records = mlb_stats_api.get_team_records()
    print_records(records)

    print("=" * 60)
    print("  Connection successful! No API key was needed.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
