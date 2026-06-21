"""
MLB Stats API fetcher — FREE, official, no API key required.
Source: https://statsapi.mlb.com

Provides:
- get_todays_games()  -> games + starting pitchers
- get_team_records()  -> current win/loss standings

STANDARD SHAPE
--------------
Every fetcher in this folder returns games in this same shape,
regardless of provider. The rest of the app (database writer,
FastAPI routes) only needs to know this shape — not which
provider the data came from. This is what lets us swap or add
providers (like SportsDataIO) later without touching other code.

game = {
    "external_game_id": str,
    "game_date":        "YYYY-MM-DD",
    "game_time":        "HH:MM" (UTC) or None,
    "status":           "scheduled" | "in_progress" | "final" | "postponed",
    "home_team":        "NYY"  (team abbreviation),
    "away_team":        "BOS",
    "home_score":       int or None,
    "away_score":       int or None,
    "home_pitcher":     str or None,
    "away_pitcher":     str or None,
}

team_record = {
    "team":         "NYY",
    "season":       2026,
    "wins":         int,
    "losses":       int,
    "home_wins":    int,
    "home_losses":  int,
    "away_wins":    int,
    "away_losses":  int,
}
"""

from datetime import date
import requests



BASE_URL = "https://statsapi.mlb.com/api/v1"

# MLB Stats API uses these IDs for the two leagues
AL_LEAGUE_ID = 103
NL_LEAGUE_ID = 104

STATUS_MAP = {
    "Scheduled": "scheduled",
    "Pre-Game": "scheduled",
    "Warmup": "scheduled",
    "In Progress": "in_progress",
    "Final": "final",
    "Game Over": "final",
    "Postponed": "postponed",
    "Suspended": "postponed",
}


def get_todays_games(target_date=None):
    """Fetch games (with probable pitchers) for a given date (default: today)."""
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": 1,  # 1 = MLB
        "date": target_date,
        "hydrate": "probablePitcher,team",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    games = []
    for date_entry in data.get("dates", []):
        schedule_date = date_entry.get("date")
        for game in date_entry.get("games", []):
            games.append(_normalize_game(game, schedule_date))

    return games


def _normalize_game(game, schedule_date):
    teams = game.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    # gameDate is the game's UTC start time. For night games (8pm+ ET),
    # its calendar date rolls to the next day, but the MLB schedule still
    # groups the game under schedule_date - use schedule_date for
    # game_date so a whole day's games share one date, and keep
    # gameDate's time-of-day for game_time.
    game_datetime = game.get("gameDate", "")
    game_time = game_datetime.split("T")[1][:5] if "T" in game_datetime else None

    detailed_status = game.get("status", {}).get("detailedState", "")

    return {
        "external_game_id": str(game.get("gamePk")),
        "game_date": schedule_date,
        "game_time": game_time,
        "status": STATUS_MAP.get(detailed_status, "scheduled"),
        "home_team": home.get("team", {}).get("abbreviation"),
        "away_team": away.get("team", {}).get("abbreviation"),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
        "home_pitcher": home.get("probablePitcher", {}).get("fullName"),
        "away_pitcher": away.get("probablePitcher", {}).get("fullName"),
    }


def get_team_records(season=None):
    """Fetch current win/loss standings for every MLB team."""
    if season is None:
        season = date.today().year

    url = f"{BASE_URL}/standings"
    params = {
        "leagueId": f"{AL_LEAGUE_ID},{NL_LEAGUE_ID}",
        "season": season,
        "hydrate": "team",
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    records = []
    for division in data.get("records", []):
        for team_record in division.get("teamRecords", []):
            records.append(_normalize_record(team_record, season))

    return records


def get_bullpen_innings(game_pk, side):
    """
    Fetch total bullpen innings pitched for one team in a completed game.

    side: 'home' or 'away'

    Returns a float in baseball IP notation: 3.1 means 3 innings + 1 out.
    Returns 0.0 if only the starter pitched (complete game).
    """
    url = f"{BASE_URL}/game/{game_pk}/boxscore"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    team_data = data.get("teams", {}).get(side, {})
    pitcher_ids = team_data.get("pitchers", [])
    players = team_data.get("players", {})

    # First entry is the starter; everything after is the bullpen.
    bullpen_ids = pitcher_ids[1:]
    total_outs = sum(
        _ip_to_outs(
            players.get(f"ID{pid}", {})
                   .get("stats", {})
                   .get("pitching", {})
                   .get("inningsPitched", "0")
        )
        for pid in bullpen_ids
    )
    return _outs_to_ip(total_outs)


def _ip_to_outs(ip_str):
    """Convert baseball IP string '6.2' (6 innings, 2 outs) to total outs (20)."""
    try:
        parts = str(ip_str).split(".")
        return int(parts[0]) * 3 + (int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return 0


def _outs_to_ip(total_outs):
    """Convert total outs to baseball IP float: 20 outs → 6.2."""
    return float(f"{total_outs // 3}.{total_outs % 3}")


def _normalize_record(team_record, season):
    team = team_record.get("team", {})

    splits = {}
    for split in team_record.get("records", {}).get("splitRecords", []):
        splits[split.get("type", "").lower()] = split

    home = splits.get("home", {})
    away = splits.get("away", {})

    return {
        "team": team.get("abbreviation"),
        "season": season,
        "wins": team_record.get("wins"),
        "losses": team_record.get("losses"),
        "home_wins": home.get("wins"),
        "home_losses": home.get("losses"),
        "away_wins": away.get("wins"),
        "away_losses": away.get("losses"),
    }
