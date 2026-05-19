"""Google Tasks API helpers — list task lists, list/create/complete/delete tasks.

Loads the OAuth token from DATA_DIR/token.json. If the token is missing or
cannot be refreshed, raises TasksAuthError with an actionable message.
"""

import datetime as dt
import logging
import os

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

logger = logging.getLogger("tasks_tools")

DATA_DIR = os.getenv("DATA_DIR", ".")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")
DEFAULT_TASK_LIST = os.getenv("GOOGLE_TASKS_LIST_ID", "@default")

_AUTH_HELP = "Tasks auth missing. Run python auth_google.py"


class TasksAuthError(Exception):
    """Raised when the Google OAuth token is missing or unusable."""


def _credentials() -> Credentials:
    """Load and (if needed) refresh the OAuth credentials from token.json."""
    if not os.path.exists(TOKEN_PATH):
        raise TasksAuthError(_AUTH_HELP)
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except Exception as exc:
        logger.error("Failed to load token.json: %s", exc)
        raise TasksAuthError(_AUTH_HELP) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as exc:
                logger.error("Token refresh failed: %s", exc)
                raise TasksAuthError(_AUTH_HELP) from exc
        else:
            raise TasksAuthError(_AUTH_HELP)
    return creds


def _service():
    """Build an authenticated Tasks API service object."""
    return build("tasks", "v1", credentials=_credentials(), cache_discovery=False)


def _humanize_due(value: str) -> str:
    """Turn an RFC3339 due timestamp into 'Tuesday May 20'."""
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        return parsed.strftime("%A %B %-d")
    except Exception:
        return value


def list_task_lists() -> list[dict]:
    """Return all available Google Task lists as {id, title} dicts."""
    service = _service()
    result = service.tasklists().list(maxResults=100).execute()
    return [
        {"id": item.get("id"), "title": item.get("title")}
        for item in result.get("items", [])
    ]


def list_tasks(task_list_id: str = "@default", show_completed: bool = False) -> list[dict]:
    """List tasks in a task list."""
    service = _service()
    list_id = task_list_id or DEFAULT_TASK_LIST
    result = service.tasks().list(
        tasklist=list_id,
        showCompleted=show_completed,
        showHidden=show_completed,
        maxResults=100,
    ).execute()

    tasks = []
    for item in result.get("items", []):
        tasks.append({
            "id": item.get("id"),
            "title": item.get("title", "(no title)"),
            "due": _humanize_due(item.get("due", "")),
            "status": item.get("status", "needsAction"),
            "notes": item.get("notes", ""),
        })
    return tasks


def create_task(
    title: str,
    task_list_id: str = "@default",
    due_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a new task. due_date is an ISO 8601 date string."""
    service = _service()
    list_id = task_list_id or DEFAULT_TASK_LIST

    body: dict = {"title": title}
    if notes:
        body["notes"] = notes
    if due_date:
        # Google Tasks expects an RFC3339 timestamp; only the date part is honored.
        body["due"] = due_date if "T" in due_date else f"{due_date}T00:00:00.000Z"

    created = service.tasks().insert(tasklist=list_id, body=body).execute()
    return {
        "task_id": created.get("id"),
        "title": created.get("title"),
        "task_list_id": list_id,
        "due": _humanize_due(created.get("due", "")),
        "status": "created",
    }


def complete_task(task_id: str, task_list_id: str) -> dict:
    """Mark a task as completed."""
    service = _service()
    list_id = task_list_id or DEFAULT_TASK_LIST
    updated = service.tasks().patch(
        tasklist=list_id,
        task=task_id,
        body={"status": "completed"},
    ).execute()
    return {
        "task_id": updated.get("id"),
        "title": updated.get("title"),
        "task_list_id": list_id,
        "status": "completed",
    }


def delete_task(task_id: str, task_list_id: str) -> dict:
    """Delete a task."""
    service = _service()
    list_id = task_list_id or DEFAULT_TASK_LIST
    service.tasks().delete(tasklist=list_id, task=task_id).execute()
    return {"task_id": task_id, "task_list_id": list_id, "status": "deleted"}
