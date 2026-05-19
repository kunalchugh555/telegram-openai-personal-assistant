"""Google Drive API helpers — search files and read file content (read-only).

Loads the OAuth token from DATA_DIR/token.json. If the token is missing or
cannot be refreshed, raises DriveAuthError with an actionable message.

The OAuth scope is drive.readonly — this module only ever reads, never writes.
File content is always truncated to CONTENT_LIMIT characters to protect GPT's
context window.
"""

import datetime as dt
import io
import logging
import os

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# pypdf is optional: if it is not installed, PDF reading degrades gracefully
# rather than crashing the module import.
try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

load_dotenv()

logger = logging.getLogger("drive_tools")

DATA_DIR = os.getenv("DATA_DIR", ".")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")

# Hard cap on returned content length, in characters.
CONTENT_LIMIT = 3000
# Sheets are returned as CSV trimmed to this many rows.
SHEET_ROW_LIMIT = 50

_AUTH_HELP = "Drive auth missing. Run python auth_google.py"

# Google MIME types mapped to plain-English labels the user would recognize.
_FRIENDLY_TYPE = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.folder": "Folder",
    "application/pdf": "PDF",
}


class DriveAuthError(Exception):
    """Raised when the Google OAuth token is missing or unusable."""


def _credentials() -> Credentials:
    """Load and (if needed) refresh the OAuth credentials from token.json."""
    if not os.path.exists(TOKEN_PATH):
        raise DriveAuthError(_AUTH_HELP)
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except Exception as exc:
        logger.error("Failed to load token.json: %s", exc)
        raise DriveAuthError(_AUTH_HELP) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as exc:
                logger.error("Token refresh failed: %s", exc)
                raise DriveAuthError(_AUTH_HELP) from exc
        else:
            raise DriveAuthError(_AUTH_HELP)
    return creds


def _service():
    """Build an authenticated Drive API service object."""
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _friendly_type(mime: str) -> str:
    """Map a MIME type to a human-readable label, falling back to the raw type."""
    return _FRIENDLY_TYPE.get(mime, mime or "unknown")


def _humanize(iso_timestamp: str) -> str:
    """Turn an ISO 8601 timestamp into 'Tuesday May 20'."""
    if not iso_timestamp:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        return parsed.strftime("%A %B %-d")
    except Exception:
        return iso_timestamp


def _read_pdf(service, file_id: str) -> str | None:
    """Download a PDF and extract its text. Returns None if extraction fails."""
    if PdfReader is None:
        logger.warning("pypdf is not installed — cannot read PDF content")
        return None
    try:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
        reader = PdfReader(buffer)
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        logger.error("PDF extraction failed for %s: %s", file_id, exc)
        return None


def search_files(query: str, max_results: int = 5) -> list[dict]:
    """Search Drive files by name or full-text content.

    Returns {id, name, type, modified_date, web_link} for each match, most
    recently modified first.
    """
    service = _service()
    # Escape backslashes and single quotes so the query string is safe to embed.
    safe = query.replace("\\", "\\\\").replace("'", "\\'")
    q = f"(name contains '{safe}' or fullText contains '{safe}') and trashed = false"

    result = service.files().list(
        q=q,
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
        orderBy="modifiedTime desc",
    ).execute()

    files = []
    for item in result.get("files", []):
        files.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "type": _friendly_type(item.get("mimeType", "")),
            "modified_date": _humanize(item.get("modifiedTime", "")),
            "web_link": item.get("webViewLink", ""),
        })
    return files


def read_file_content(file_id: str) -> dict:
    """Read the text content of a Drive file.

    Google Docs export as plain text, Sheets export as CSV (first 50 rows), and
    PDFs have their text extracted. Any other type returns an error payload.
    Content is always truncated to CONTENT_LIMIT characters.
    """
    service = _service()
    meta = service.files().get(
        fileId=file_id, fields="name, mimeType, modifiedTime"
    ).execute()
    name = meta.get("name", "(unknown)")
    mime = meta.get("mimeType", "")

    if mime == "application/vnd.google-apps.document":
        raw = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    elif mime == "application/vnd.google-apps.spreadsheet":
        raw = service.files().export(fileId=file_id, mimeType="text/csv").execute()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        rows = text.splitlines()
        content = "\n".join(rows[:SHEET_ROW_LIMIT])
        if len(rows) > SHEET_ROW_LIMIT:
            content += f"\n[Showing first {SHEET_ROW_LIMIT} rows]"

    elif mime == "application/pdf":
        extracted = _read_pdf(service, file_id)
        if extracted is None:
            return {
                "error": "Cannot read this file type",
                "name": name,
                "modified_date": _humanize(meta.get("modifiedTime", "")),
            }
        content = extracted

    else:
        # Slides, images, archives, etc. — not readable as text here.
        return {
            "error": "Cannot read this file type",
            "name": name,
            "modified_date": _humanize(meta.get("modifiedTime", "")),
        }

    truncated = len(content) > CONTENT_LIMIT
    if truncated:
        content = content[:CONTENT_LIMIT] + f"\n[Content truncated at {CONTENT_LIMIT} characters]"
    return {"name": name, "content": content, "truncated": truncated}
