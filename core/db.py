"""SQLite-backed conversation history, one row per message, scoped per user ID."""

import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "assistant.db")


def _connect() -> sqlite3.Connection:
    """Open a connection and ensure the messages table exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY,
            user_id   INTEGER NOT NULL,
            role      TEXT    NOT NULL,
            content   TEXT    NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn


def get_history(user_id: int, limit: int = 20) -> list[dict]:
    """Return the last `limit` messages for a user as {role, content} dicts, oldest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (user_id, limit),
        ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]
    finally:
        conn.close()


def add_message(user_id: int, role: str, content: str) -> None:
    """Append a single message to the history."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        conn.commit()
    finally:
        conn.close()


def trim_history(user_id: int, keep: int = 20) -> None:
    """Delete all but the most recent `keep` messages for a user (drop oldest first)."""
    conn = _connect()
    try:
        conn.execute(
            """
            DELETE FROM messages
            WHERE user_id = ?
              AND id NOT IN (
                SELECT id FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (user_id, user_id, keep),
        )
        conn.commit()
    finally:
        conn.close()


def clear_history(user_id: int) -> None:
    """Remove all stored messages for a user."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
