"""Google Calendar API helpers — list, create, update, delete events.

Loads the OAuth token from DATA_DIR/token.json. If the token is missing or
cannot be refreshed, raises CalendarAuthError with an actionable message.
"""

import datetime as dt
import logging
import os
import uuid
import zoneinfo

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

logger = logging.getLogger("calendar_tools")

DATA_DIR = os.getenv("DATA_DIR", ".")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

_AUTH_HELP = "Calendar auth missing. Run python auth_google.py"


class CalendarAuthError(Exception):
    """Raised when the Google OAuth token is missing or unusable."""


def _credentials() -> Credentials:
    """Load and (if needed) refresh the OAuth credentials from token.json."""
    if not os.path.exists(TOKEN_PATH):
        raise CalendarAuthError(_AUTH_HELP)
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except Exception as exc:
        logger.error("Failed to load token.json: %s", exc)
        raise CalendarAuthError(_AUTH_HELP) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as exc:
                logger.error("Token refresh failed: %s", exc)
                raise CalendarAuthError(_AUTH_HELP) from exc
        else:
            raise CalendarAuthError(_AUTH_HELP)
    return creds


def _service():
    """Build an authenticated Calendar API service object."""
    return build("calendar", "v3", credentials=_credentials(), cache_discovery=False)


def _calendar_timezone(service) -> str:
    """Return the calendar's configured timezone, defaulting to UTC."""
    try:
        cal = service.calendars().get(calendarId=CALENDAR_ID).execute()
        return cal.get("timeZone", "UTC")
    except Exception as exc:
        logger.warning("Could not read calendar timezone, defaulting to UTC: %s", exc)
        return "UTC"


def _humanize(value: str) -> str:
    """Turn an ISO date/datetime string into 'Tuesday May 20 at 2:00 PM' in USER_TIMEZONE."""
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        if "T" not in value:
            return parsed.strftime("%A %B %-d")
        if parsed.tzinfo is not None:
            try:
                tz = zoneinfo.ZoneInfo(os.getenv("USER_TIMEZONE", "America/Chicago"))
                parsed = parsed.astimezone(tz)
            except Exception:
                pass
        return parsed.strftime("%A %B %-d at %-I:%M %p")
    except Exception:
        return value


def list_events(start_date: str, end_date: str) -> list[dict]:
    """List events between two ISO 8601 dates/datetimes (inclusive).

    When start_date is a bare date (no time) and matches today, we use the
    current UTC time so that events already passed today are excluded — this
    makes 'next meeting' queries return only future events.
    """
    service = _service()
    if "T" in start_date:
        time_min = start_date
    else:
        today_iso = dt.date.today().isoformat()
        if start_date == today_iso:
            # Use right now so past-today events are excluded.
            time_min = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            time_min = f"{start_date}T00:00:00Z"
    time_max = end_date if "T" in end_date else f"{end_date}T23:59:59Z"

    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    events = []
    for item in result.get("items", []):
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
        end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", "")
        events.append({
            "id": item.get("id"),
            "title": item.get("summary", "(no title)"),
            "start": _humanize(start),
            "end": _humanize(end),
            "raw_start": start,
            "raw_end": end,
        })
    return events


def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    add_meet_link: bool = False,
) -> dict:
    """Create a calendar event and return its ID plus a human-readable time.

    Pass add_meet_link=True to automatically generate a Google Meet link.
    """
    service = _service()
    timezone = _calendar_timezone(service)
    body = {
        "summary": title,
        "description": description or "",
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
    }
    if add_meet_link:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    created = service.events().insert(
        calendarId=CALENDAR_ID,
        body=body,
        conferenceDataVersion=1 if add_meet_link else 0,
    ).execute()

    result = {
        "event_id": created.get("id"),
        "title": created.get("summary"),
        "start": _humanize(start_datetime),
        "end": _humanize(end_datetime),
        "status": "created",
    }
    if add_meet_link:
        for ep in created.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                result["meet_link"] = ep.get("uri")
                break
    return result


def update_event(
    event_id: str,
    title: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
) -> dict:
    """Update fields of an existing event by ID. Only provided fields change."""
    service = _service()
    timezone = _calendar_timezone(service)

    body: dict = {}
    if title is not None:
        body["summary"] = title
    if start_datetime is not None:
        body["start"] = {"dateTime": start_datetime, "timeZone": timezone}
    if end_datetime is not None:
        body["end"] = {"dateTime": end_datetime, "timeZone": timezone}

    if not body:
        return {"event_id": event_id, "status": "no_changes"}

    updated = service.events().patch(
        calendarId=CALENDAR_ID, eventId=event_id, body=body
    ).execute()

    start = updated.get("start", {}).get("dateTime") or updated.get("start", {}).get("date", "")
    end = updated.get("end", {}).get("dateTime") or updated.get("end", {}).get("date", "")
    return {
        "event_id": updated.get("id"),
        "title": updated.get("summary"),
        "start": _humanize(start),
        "end": _humanize(end),
        "status": "updated",
    }


def delete_event(event_id: str) -> dict:
    """Delete an event by ID."""
    service = _service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return {"event_id": event_id, "status": "deleted"}
