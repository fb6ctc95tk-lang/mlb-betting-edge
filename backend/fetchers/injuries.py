"""
ESPN injury fetcher — unofficial but stable, no API key required.
https://site.api.espn.com

get_mlb_injuries() returns a list of injury records across all MLB teams:

injury = {
    "team_abbreviation": "NYY",
    "player_name":        "Aaron Judge",
    "injury_status":      "10-Day IL",
    "injury_description": "Right hip inflammation.",
}

Failures raise requests.HTTPError. Callers should catch and skip gracefully.
"""

import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"

# ESPN uses OAK; our system uses ATH for the Sacramento Athletics.
_ABBR_MAP = {
    "OAK": "ATH",
}


def get_mlb_injuries():
    response = requests.get(URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    results = []
    for team_block in data.get("injuries", []):
        espn_abbr = team_block.get("team", {}).get("abbreviation", "")
        abbr = _ABBR_MAP.get(espn_abbr, espn_abbr)

        for entry in team_block.get("injuries", []):
            athlete = entry.get("athlete", {})
            player_name = athlete.get("fullName") or athlete.get("displayName", "")
            if not player_name:
                continue

            status = entry.get("status") or entry.get("type", {}).get("description", "")
            description = entry.get("longComment") or entry.get("shortComment", "")

            results.append({
                "team_abbreviation": abbr,
                "player_name": player_name,
                "injury_status": status or None,
                "injury_description": description or None,
            })

    return results
