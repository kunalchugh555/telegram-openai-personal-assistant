"""Weather helpers backed by the free Open-Meteo API — no API key required.

Geocoding uses Open-Meteo's geocoding endpoint; forecasts use its forecast
endpoint. All temperatures are Fahrenheit and wind speeds are mph (US units).

On any network or API failure, these functions return an {"error": ...}
payload (rather than raising) so the assistant relays a friendly message.
"""

import datetime as dt
import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("weather_tools")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 10  # seconds

# Shown to the user when the weather API cannot be reached.
WEATHER_ERROR = "I couldn't fetch the weather right now. Try again in a moment."

# Open-Meteo free tier serves at most 7 days of daily forecast.
MAX_FORECAST_DAYS = 7

# WMO weather interpretation codes mapped to plain English.
# Reference: https://open-meteo.com/en/docs (Weather variable documentation)
_WMO_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def _condition(code) -> str:
    """Translate a WMO weather code into a plain-English condition."""
    try:
        return _WMO_CODES.get(int(code), "unknown")
    except (TypeError, ValueError):
        return "unknown"


def _round(value):
    """Round a numeric value to the nearest integer, or None if not numeric."""
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _percent(value) -> str:
    """Format a precipitation probability as a percent string."""
    rounded = _round(value)
    return f"{rounded}%" if rounded is not None else "unknown"


def _weekday(iso_date: str) -> str:
    """Turn an ISO date (YYYY-MM-DD) into a weekday name."""
    try:
        return dt.datetime.fromisoformat(iso_date).strftime("%A")
    except Exception:
        return iso_date


def _geocode(location: str):
    """Resolve a place name to (latitude, longitude, label). Returns None if not found.

    Open-Meteo's geocoder matches a single place name and rejects "City, State"
    style strings, so if the full string finds nothing we retry with just the
    text before the first comma (e.g. "Dubuque, Iowa" -> "Dubuque").
    """
    candidates = [location.strip()]
    if "," in location:
        candidates.append(location.split(",")[0].strip())

    for candidate in candidates:
        if not candidate:
            continue
        resp = requests.get(
            GEOCODE_URL, params={"name": candidate, "count": 1}, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if results:
            top = results[0]
            label = ", ".join(
                part for part in
                (top.get("name"), top.get("admin1"), top.get("country_code"))
                if part
            )
            return top["latitude"], top["longitude"], label
    return None


def _format_weather(data: dict, label: str) -> dict:
    """Shape a raw Open-Meteo forecast response into the assistant-friendly dict."""
    current = data.get("current", {})
    daily = data.get("daily", {})

    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    def at(seq, i):
        """Safe indexed access — None when the list is shorter than expected."""
        return seq[i] if i < len(seq) else None

    week = []
    for i, day in enumerate(times):
        week.append({
            "day": _weekday(day),
            "high": _round(at(highs, i)),
            "low": _round(at(lows, i)),
            "condition": _condition(at(codes, i)),
            "precip_chance": _percent(at(precip, i)),
        })

    today = week[0] if week else {}
    return {
        "location": label,
        "current": {
            "temp": _round(current.get("temperature_2m")),
            "feels_like": _round(current.get("apparent_temperature")),
            "condition": _condition(current.get("weathercode")),
            "wind_mph": _round(current.get("windspeed_10m")),
        },
        "today": {
            "high": today.get("high"),
            "low": today.get("low"),
            "precip_chance": today.get("precip_chance"),
            "condition": today.get("condition"),
        },
        "week": week,
    }


def get_weather(
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Get current conditions plus a 7-day forecast for a location.

    Coordinates are used directly when given; otherwise the location string (or
    USER_LOCATION from the environment) is geocoded first. All units are US.
    """
    try:
        label = location or ""

        # Resolve coordinates if they were not supplied directly.
        if lat is None or lon is None:
            place = location or os.getenv("USER_LOCATION", "")
            if not place:
                return {"error": "No location given and USER_LOCATION is not set."}
            geo = _geocode(place)
            if geo is None:
                return {"error": f"I couldn't find a place called '{place}'."}
            lat, lon, label = geo

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weathercode,windspeed_10m",
            "hourly": (
                "temperature_2m,precipitation_probability,weathercode,"
                "windspeed_10m,apparent_temperature"
            ),
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weathercode"
            ),
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "timezone": "auto",
            "forecast_days": MAX_FORECAST_DAYS,
        }
        resp = requests.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return _format_weather(resp.json(), label or f"{lat},{lon}")

    except requests.RequestException as exc:
        logger.error("Weather request failed: %s", exc)
        return {"error": WEATHER_ERROR}
    except Exception as exc:
        logger.error("Weather processing failed: %s", exc)
        return {"error": WEATHER_ERROR}


def get_forecast(days: int = 7, location: str | None = None) -> dict:
    """Return a multi-day forecast (the `week` array), capped at 7 days."""
    try:
        days = max(1, min(int(days or MAX_FORECAST_DAYS), MAX_FORECAST_DAYS))
    except (TypeError, ValueError):
        days = MAX_FORECAST_DAYS

    weather = get_weather(location=location)
    if "error" in weather:
        return weather
    return {"location": weather["location"], "forecast": weather["week"][:days]}
