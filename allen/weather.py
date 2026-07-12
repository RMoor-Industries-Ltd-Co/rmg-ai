"""Weather lookup for the morning briefing — National Weather Service (api.weather.gov),
no API key required. Grounded to Rahm's home coordinates (Villa Rica, GA)."""

import json
import urllib.error
import urllib.request

HOME_LAT = 33.7315
HOME_LON = -84.9177  # Villa Rica, GA
FORECAST_PAGE_URL = f"https://forecast.weather.gov/MapClick.php?lat={HOME_LAT}&lon={HOME_LON}"


def _get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ALLEN-RMG/1.0 (weather, contact: rahm@rmasters.group)", "Accept": "application/geo+json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def todays_forecast() -> str:
    """Short text summary of today's day/night forecast for home, or an error note —
    never raises, since the briefing must still generate without weather if this fails."""
    try:
        points = _get(f"https://api.weather.gov/points/{HOME_LAT},{HOME_LON}")
        forecast_url = points["properties"]["forecast"]
        data = _get(forecast_url)
        periods = data["properties"]["periods"][:2]  # today (day) + tonight
        lines = []
        for p in periods:
            precip = (p.get("probabilityOfPrecipitation") or {}).get("value")
            precip_note = f" — {precip}% chance of precipitation" if precip else ""
            lines.append(
                f"{p['name']}: {p['temperature']}°{p['temperatureUnit']}, {p['shortForecast']}{precip_note}. "
                f"{p['detailedForecast']}"
            )
        lines.append(f"Full forecast: {FORECAST_PAGE_URL}")
        return "\n".join(lines)
    except (urllib.error.URLError, KeyError, ValueError, TypeError) as e:
        return f"(weather lookup failed: {e})"
