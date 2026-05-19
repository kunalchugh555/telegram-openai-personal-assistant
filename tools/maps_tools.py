"""Google Maps helpers — travel time/directions and nearby place search.

Requires a Google Maps Platform API key (GOOGLE_MAPS_API_KEY in .env).
Enable in Google Cloud Console:
  - Directions API
  - Places API
"""

import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("maps_tools")

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
HTTP_TIMEOUT = 10

MAPS_ERROR = "I couldn't reach Google Maps right now. Try again in a moment."


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise ValueError("GOOGLE_MAPS_API_KEY is not set in .env.")
    return key


def get_travel_time(
    origin: str,
    destination: str,
    mode: str = "driving",
) -> dict:
    """Get travel time and distance between two places.

    mode: "driving" | "walking" | "bicycling" | "transit"
    """
    try:
        resp = requests.get(
            DIRECTIONS_URL,
            params={"origin": origin, "destination": destination, "mode": mode, "key": _api_key()},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            return {"error": f"No route found ({data.get('status')})."}

        leg = data["routes"][0]["legs"][0]
        return {
            "origin": leg["start_address"],
            "destination": leg["end_address"],
            "mode": mode,
            "duration": leg["duration"]["text"],
            "distance": leg["distance"]["text"],
        }
    except ValueError as exc:
        return {"error": str(exc)}
    except requests.RequestException as exc:
        logger.error("Maps directions request failed: %s", exc)
        return {"error": MAPS_ERROR}
    except Exception as exc:
        logger.error("Maps travel time failed: %s", exc)
        return {"error": MAPS_ERROR}


def search_nearby(query: str, location: str | None = None) -> dict:
    """Search Google Maps for places matching a query.

    Biases results toward `location` when provided; falls back to USER_LOCATION.
    """
    try:
        bias = location or os.getenv("USER_LOCATION", "")
        search_query = f"{query} near {bias}" if bias else query

        resp = requests.get(
            PLACES_URL,
            params={"query": search_query, "key": _api_key()},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            return {"error": f"Places search failed ({data.get('status')})."}

        places = []
        for place in data.get("results", [])[:5]:
            places.append({
                "name": place.get("name"),
                "address": place.get("formatted_address"),
                "rating": place.get("rating"),
                "open_now": place.get("opening_hours", {}).get("open_now"),
            })
        return {"query": search_query, "places": places}
    except ValueError as exc:
        return {"error": str(exc)}
    except requests.RequestException as exc:
        logger.error("Maps places request failed: %s", exc)
        return {"error": MAPS_ERROR}
    except Exception as exc:
        logger.error("Maps places search failed: %s", exc)
        return {"error": MAPS_ERROR}
