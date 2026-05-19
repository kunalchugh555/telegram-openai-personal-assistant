"""Weather helpers backed by the free Open-Meteo API — no API key required.

Geocoding uses Open-Meteo's geocoding endpoint; forecasts use its forecast
endpoint. All temperatures are Fahrenheit and wind speeds are mph (US units).

Coverage:
  - get_weather          current conditions, today, the next 14 days, and the
                         past 7 days (daily summaries)
  - get_forecast         a multi-day daily forecast (future), capped at 14 days
  - get_hourly_forecast  hour-by-hour detail for a single day — any day within
                         the last 92 days or the next 14 days

Note: forecasts beyond ~7 days out are lower confidence — Open-Meteo serves
them from a coarser model.

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

# Open-Meteo serves up to 16 forecast days and 92 days of history; we use 14.
MAX_FORECAST_DAYS = 14
PAST_WEEK_DAYS = 7      # past days bundled into a get_weather response
MAX_PAST_DAYS = 92      # furthest back the forecast endpoint serves history

# Field lists requested from the Open-Meteo forecast endpoint.
CURRENT_FIELDS = "temperature_2m,apparent_temperature,weathercode,windspeed_10m"
HOURLY_FIELDS = (
    "temperature_2m,precipitation_probability,weathercode,"
    "windspeed_10m,apparent_temperature"
)
DAILY_FIELDS = (
    "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
)

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


def _at(seq, i):
    """Safe indexed access — returns None when the list is shorter than expected."""
    return seq[i] if i < len(seq) else None


def _weekday(iso_date: str) -> str:
    """Turn an ISO date (YYYY-MM-DD) into a weekday name."""
    try:
        return dt.datetime.fromisoformat(iso_date).strftime("%A")
    except Exception:
        return iso_date


def _format_hour(iso_datetime: str) -> str:
    """Turn an ISO datetime (YYYY-MM-DDTHH:MM) into a clock time like '3:00 PM'."""
    try:
        return dt.datetime.fromisoformat(iso_datetime).strftime("%-I:%M %p")
    except Exception:
        return iso_datetime


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


def _resolve_coords(location: str | None, lat: float | None, lon: float | None):
    """Return (lat, lon, label) for a request.

    Coordinates are used directly when supplied; otherwise the location string
    (or USER_LOCATION from the environment) is geocoded. Raises ValueError with
    a user-facing message when the location cannot be determined.
    """
    if lat is not None and lon is not None:
        return lat, lon, location or f"{lat}, {lon}"

    place = location or os.getenv("USER_LOCATION", "")
    if not place:
        raise ValueError("No location given and USER_LOCATION is not set.")

    geo = _geocode(place)
    if geo is None:
        raise ValueError(f"I couldn't find a place called '{place}'.")
    return geo


def _format_weather(data: dict, label: str) -> dict:
    """Shape a raw Open-Meteo response into the assistant-friendly weather dict.

    The daily arrays span past days then forecast days; today's index is found
    by date so the result can be split into `past` and `week` (today onward).
    """
    current = data.get("current", {})
    daily = data.get("daily", {})

    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_probability_max", [])
    codes = daily.get("weathercode", [])

    def day_entry(i: int) -> dict:
        return {
            "day": _weekday(times[i]),
            "date": times[i],
            "high": _round(_at(highs, i)),
            "low": _round(_at(lows, i)),
            "condition": _condition(_at(codes, i)),
            "precip_chance": _percent(_at(precip, i)),
        }

    all_days = [day_entry(i) for i in range(len(times))]

    # Split into past vs. today-onward using today's date as the anchor.
    today_iso = dt.date.today().isoformat()
    today_idx = times.index(today_iso) if today_iso in times else 0
    past = all_days[:today_idx]
    week = all_days[today_idx:]
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
        "week": week,   # today plus the next 13 days
        "past": past,   # the previous 7 days
    }


def _format_hourly(data: dict, label: str, target: dt.date) -> dict:
    """Pull the 24 hourly entries for `target` from a raw Open-Meteo response."""
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    feels = hourly.get("apparent_temperature", [])
    codes = hourly.get("weathercode", [])
    precip = hourly.get("precipitation_probability", [])
    wind = hourly.get("windspeed_10m", [])

    prefix = target.isoformat()  # hourly times look like "2026-05-19T15:00"
    hours = []
    for i, stamp in enumerate(times):
        if not stamp.startswith(prefix):
            continue
        hours.append({
            "time": _format_hour(stamp),
            "temp": _round(_at(temps, i)),
            "feels_like": _round(_at(feels, i)),
            "condition": _condition(_at(codes, i)),
            "precip_chance": _percent(_at(precip, i)),
            "wind_mph": _round(_at(wind, i)),
        })

    if not hours:
        return {"error": "I don't have hourly data for that date."}
    return {
        "location": label,
        "date": target.strftime("%A %B %-d"),
        "hours": hours,
    }


def get_weather(
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Get current conditions, today, the next 14 days, and the past 7 days.

    Coordinates are used directly when given; otherwise the location string (or
    USER_LOCATION from the environment) is geocoded first. All units are US.
    """
    try:
        lat, lon, label = _resolve_coords(location, lat, lon)
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": CURRENT_FIELDS,
            "hourly": HOURLY_FIELDS,
            "daily": DAILY_FIELDS,
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "timezone": "auto",
            "forecast_days": MAX_FORECAST_DAYS,
            "past_days": PAST_WEEK_DAYS,
        }
        resp = requests.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return _format_weather(resp.json(), label)

    except ValueError as exc:
        # Raised by _resolve_coords with a user-facing message.
        return {"error": str(exc)}
    except requests.RequestException as exc:
        logger.error("Weather request failed: %s", exc)
        return {"error": WEATHER_ERROR}
    except Exception as exc:
        logger.error("Weather processing failed: %s", exc)
        return {"error": WEATHER_ERROR}


def get_forecast(days: int = 7, location: str | None = None) -> dict:
    """Return a multi-day daily forecast (the `week` array), capped at 7 days."""
    try:
        days = max(1, min(int(days or MAX_FORECAST_DAYS), MAX_FORECAST_DAYS))
    except (TypeError, ValueError):
        days = MAX_FORECAST_DAYS

    weather = get_weather(location=location)
    if "error" in weather:
        return weather
    return {"location": weather["location"], "forecast": weather["week"][:days]}


def get_hourly_forecast(
    date: str | None = None,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Get hour-by-hour weather for a single day.

    `date` is an ISO date string (YYYY-MM-DD); it defaults to today. Works for
    past days up to 92 days back and future days up to 7 days ahead.
    """
    # Parse and validate the requested date.
    try:
        target = dt.date.fromisoformat(date) if date else dt.date.today()
    except (TypeError, ValueError):
        return {"error": f"'{date}' is not a valid date — use YYYY-MM-DD."}

    today = dt.date.today()
    delta = (target - today).days  # negative = past, 0 = today, positive = future
    if delta > MAX_FORECAST_DAYS - 1:
        return {"error": f"I can only forecast up to {MAX_FORECAST_DAYS} days ahead."}
    if delta < -MAX_PAST_DAYS:
        return {"error": f"I only have weather history for the last {MAX_PAST_DAYS} days."}

    # Request just enough range to include the target day.
    past_days = min(-delta, MAX_PAST_DAYS) if delta < 0 else 0
    forecast_days = (delta + 1) if delta >= 0 else 1

    try:
        lat, lon, label = _resolve_coords(location, lat, lon)
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": HOURLY_FIELDS,
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "timezone": "auto",
            "past_days": past_days,
            "forecast_days": forecast_days,
        }
        resp = requests.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return _format_hourly(resp.json(), label, target)

    except ValueError as exc:
        # Raised by _resolve_coords with a user-facing message.
        return {"error": str(exc)}
    except requests.RequestException as exc:
        logger.error("Hourly weather request failed: %s", exc)
        return {"error": WEATHER_ERROR}
    except Exception as exc:
        logger.error("Hourly weather processing failed: %s", exc)
        return {"error": WEATHER_ERROR}
