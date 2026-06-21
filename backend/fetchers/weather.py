"""
Open-Meteo weather fetcher — free, no API key required.
https://open-meteo.com

get_weather(lat, lon) returns current conditions at the given coordinates:
{
    "temperature":          float | None,   # °F
    "wind_speed":           float | None,   # mph
    "wind_direction":       int   | None,   # degrees (0-360)
    "precipitation_chance": int   | None,   # % for current hour
}

STADIUM_COORDS maps each MLB team abbreviation to (latitude, longitude)
for its home stadium. Used by the ingestion script to look up coords.
"""

import requests

BASE_URL = "https://api.open-meteo.com/v1/forecast"

STADIUM_COORDS = {
    "AZ":  (33.4453, -112.0667),   # Chase Field, Phoenix
    "ATL": (33.8908,  -84.4678),   # Truist Park, Cumberland
    "BAL": (39.2839,  -76.6222),   # Camden Yards, Baltimore
    "BOS": (42.3467,  -71.0972),   # Fenway Park, Boston
    "CHC": (41.9484,  -87.6553),   # Wrigley Field, Chicago
    "CWS": (41.8299,  -87.6338),   # Guaranteed Rate Field, Chicago
    "CIN": (39.0979,  -84.5082),   # Great American Ball Park, Cincinnati
    "CLE": (41.4962,  -81.6853),   # Progressive Field, Cleveland
    "COL": (39.7559, -104.9942),   # Coors Field, Denver
    "DET": (42.3390,  -83.0485),   # Comerica Park, Detroit
    "HOU": (29.7572,  -95.3555),   # Minute Maid Park, Houston
    "KC":  (39.0516,  -94.4803),   # Kauffman Stadium, Kansas City
    "LAA": (33.8003, -117.8827),   # Angel Stadium, Anaheim
    "LAD": (34.0739, -118.2400),   # Dodger Stadium, Los Angeles
    "MIA": (25.7781,  -80.2197),   # loanDepot park, Miami
    "MIL": (43.0280,  -87.9712),   # American Family Field, Milwaukee
    "MIN": (44.9817,  -93.2783),   # Target Field, Minneapolis
    "NYM": (40.7571,  -73.8458),   # Citi Field, Queens
    "NYY": (40.8296,  -73.9262),   # Yankee Stadium, Bronx
    "ATH": (38.5805, -121.5005),   # Sutter Health Park, Sacramento
    "OAK": (38.5805, -121.5005),   # Sutter Health Park, Sacramento
    "PHI": (39.9061,  -75.1665),   # Citizens Bank Park, Philadelphia
    "PIT": (40.4469,  -80.0057),   # PNC Park, Pittsburgh
    "SD":  (32.7076, -117.1570),   # Petco Park, San Diego
    "SF":  (37.7786, -122.3893),   # Oracle Park, San Francisco
    "SEA": (47.5914, -122.3325),   # T-Mobile Park, Seattle
    "STL": (38.6226,  -90.1928),   # Busch Stadium, St. Louis
    "TB":  (27.7682,  -82.6534),   # Tropicana Field, St. Petersburg
    "TEX": (32.7473,  -97.0831),   # Globe Life Field, Arlington
    "TOR": (43.6414,  -79.3894),   # Rogers Centre, Toronto
    "WSH": (38.8730,  -77.0074),   # Nationals Park, Washington
}


def get_weather(lat, lon):
    """Fetch current weather at (lat, lon). Returns a dict with four fields."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,windspeed_10m,winddirection_10m",
        "hourly": "precipitation_probability",
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "timezone": "auto",
        "forecast_days": 1,
    }

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    current = data.get("current", {})
    current_time = current.get("time", "")

    hourly_times = data.get("hourly", {}).get("time", [])
    hourly_precip = data.get("hourly", {}).get("precipitation_probability", [])

    precip_chance = None
    if current_time and current_time in hourly_times:
        idx = hourly_times.index(current_time)
        if idx < len(hourly_precip):
            precip_chance = hourly_precip[idx]

    raw_direction = current.get("winddirection_10m")

    return {
        "temperature": current.get("temperature_2m"),
        "wind_speed": current.get("windspeed_10m"),
        "wind_direction": int(raw_direction) if raw_direction is not None else None,
        "precipitation_chance": precip_chance,
    }
