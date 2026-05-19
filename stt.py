"""Speech-to-text using the OpenAI transcription API."""

import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("stt")

TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily create the OpenAI client so the API key is read after .env loads."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def transcribe(audio_path: str) -> str:
    """Transcribe an audio file to text. Raises RuntimeError on failure."""
    try:
        with open(audio_path, "rb") as audio_file:
            result = _get_client().audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=audio_file,
            )
        text = (result.text or "").strip()
        if not text:
            raise RuntimeError("Transcription returned empty text")
        return text
    except Exception as exc:
        logger.error("Transcription failed for %s: %s", audio_path, exc)
        raise RuntimeError(f"Transcription failed: {exc}") from exc
