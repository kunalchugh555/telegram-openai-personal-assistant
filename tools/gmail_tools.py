"""Google Gmail API helpers — list unread, search, read threads, draft, and send.

Loads the OAuth token from DATA_DIR/token.json. If the token is missing or
cannot be refreshed, raises GmailAuthError with an actionable message.

Two ways to compose mail:
  - create_draft  — stages a draft only; it never sends. Use when the user
    says "draft a reply" or otherwise wants to review before sending.
  - send_email    — sends immediately via the Gmail API. Only invoked when the
    user explicitly asks to send rather than draft.
"""

import base64
import datetime as dt
import logging
import os
import re
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

logger = logging.getLogger("gmail_tools")

DATA_DIR = os.getenv("DATA_DIR", ".")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")

# Bodies and snippets are capped so a long email cannot flood GPT's context.
SNIPPET_LIMIT = 150
THREAD_BODY_LIMIT = 2000

_AUTH_HELP = "Gmail auth missing. Run python auth_google.py"


class GmailAuthError(Exception):
    """Raised when the Google OAuth token is missing or unusable."""


def _credentials() -> Credentials:
    """Load and (if needed) refresh the OAuth credentials from token.json."""
    if not os.path.exists(TOKEN_PATH):
        raise GmailAuthError(_AUTH_HELP)
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    except Exception as exc:
        logger.error("Failed to load token.json: %s", exc)
        raise GmailAuthError(_AUTH_HELP) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as exc:
                logger.error("Token refresh failed: %s", exc)
                raise GmailAuthError(_AUTH_HELP) from exc
        else:
            raise GmailAuthError(_AUTH_HELP)
    return creds


def _service():
    """Build an authenticated Gmail API service object."""
    return build("gmail", "v1", credentials=_credentials(), cache_discovery=False)


# --- Parsing helpers -------------------------------------------------------------

def _header(headers: list[dict], name: str) -> str:
    """Return the value of a named header (case-insensitive) from a payload."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _humanize_email_date(raw: str) -> str:
    """Turn an RFC 2822 Date header into 'Today at 9:15 AM' / 'Monday May 12'."""
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return raw
    if parsed is None:
        return raw

    now = dt.datetime.now(parsed.tzinfo) if parsed.tzinfo else dt.datetime.now()
    if parsed.date() == now.date():
        return parsed.strftime("Today at %-I:%M %p")
    if parsed.date() == (now.date() - dt.timedelta(days=1)):
        return parsed.strftime("Yesterday at %-I:%M %p")
    return parsed.strftime("%A %B %-d")


def _decode(data: str) -> str:
    """Decode a base64url-encoded Gmail body part to text."""
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    """Reduce an HTML body to readable plain text — no tags, collapsed whitespace."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)  # drop script/style blocks
    text = re.sub(r"(?s)<[^>]+>", " ", text)                  # drop all remaining tags
    replacements = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _walk_parts(payload: dict):
    """Yield a payload and every nested part, depth-first."""
    yield payload
    for part in payload.get("parts", []):
        yield from _walk_parts(part)


def _extract_plain_body(payload: dict) -> str:
    """Pull readable text from a message payload, preferring text/plain over HTML."""
    plain = None
    html = None
    for part in _walk_parts(payload):
        data = part.get("body", {}).get("data")
        if not data:
            continue
        mime = part.get("mimeType", "")
        if mime == "text/plain" and plain is None:
            plain = _decode(data)
        elif mime == "text/html" and html is None:
            html = _strip_html(_decode(data))
    return plain or html or ""


def _summarize_message(service, message_id: str) -> dict:
    """Fetch header metadata + snippet for a single message id."""
    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    headers = msg.get("payload", {}).get("headers", [])
    return {
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "from": _header(headers, "From"),
        "subject": _header(headers, "Subject") or "(no subject)",
        "date": _humanize_email_date(_header(headers, "Date")),
        "snippet": (msg.get("snippet", "") or "")[:SNIPPET_LIMIT],
    }


def _build_mime(to: str, subject: str, body: str) -> str:
    """Build a plain-text MIME message and return it base64url-encoded for Gmail."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


# --- Public tool functions -------------------------------------------------------

def list_unread_emails(max_results: int = 10) -> list[dict]:
    """List unread inbox emails as {id, thread_id, from, subject, date, snippet}."""
    service = _service()
    listing = service.users().messages().list(
        userId="me", q="is:unread in:inbox", maxResults=max_results
    ).execute()
    return [_summarize_message(service, m["id"]) for m in listing.get("messages", [])]


def search_emails(query: str, max_results: int = 5) -> list[dict]:
    """Search emails using Gmail query syntax (e.g. 'from:john invoice')."""
    service = _service()
    listing = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return [_summarize_message(service, m["id"]) for m in listing.get("messages", [])]


def get_email_thread(thread_id: str) -> dict:
    """Read a full email thread as {subject, messages:[{from, date, body}]}.

    Messages are ordered oldest to newest; each body is plain text, truncated.
    """
    service = _service()
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="full"
    ).execute()

    subject = ""
    messages = []
    for msg in thread.get("messages", []):
        headers = msg.get("payload", {}).get("headers", [])
        if not subject:
            subject = _header(headers, "Subject") or "(no subject)"
        body = _extract_plain_body(msg.get("payload", {}))
        messages.append({
            "from": _header(headers, "From"),
            "date": _humanize_email_date(_header(headers, "Date")),
            "body": body[:THREAD_BODY_LIMIT],
        })
    return {"subject": subject, "messages": messages}


def create_draft(
    to: str,
    subject: str,
    body: str,
    reply_to_thread_id: str | None = None,
) -> dict:
    """Create a Gmail draft. This never sends — drafts only, for user safety.

    If reply_to_thread_id is given, the draft is attached to that thread.
    """
    service = _service()
    message_body: dict = {"raw": _build_mime(to, subject, body)}
    if reply_to_thread_id:
        message_body["threadId"] = reply_to_thread_id

    draft = service.users().drafts().create(
        userId="me", body={"message": message_body}
    ).execute()
    return {
        "draft_id": draft.get("id"),
        "to": to,
        "subject": subject,
        "preview": body[:100],
    }


def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to_thread_id: str | None = None,
) -> dict:
    """Compose and send an email immediately via the Gmail API.

    Unlike create_draft, this delivers the message right away. It is only
    invoked when the user explicitly asks to send rather than draft. If
    reply_to_thread_id is given, the message is sent as a reply on that thread.
    """
    service = _service()
    message_body: dict = {"raw": _build_mime(to, subject, body)}
    if reply_to_thread_id:
        message_body["threadId"] = reply_to_thread_id

    sent = service.users().messages().send(userId="me", body=message_body).execute()
    return {
        "message_id": sent.get("id"),
        "to": to,
        "subject": subject,
        "sent_at": dt.datetime.now().astimezone().strftime("%A %B %-d at %-I:%M %p"),
    }
