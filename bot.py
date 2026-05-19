"""Main entry point — a private Telegram voice/text assistant bot (polling mode).

Voice notes and uploaded audio files are transcribed with OpenAI; text messages
are used directly. Both paths are answered by GPT with Calendar and Tasks tool
calling. Only ALLOWED_USER_ID may interact with the bot; all other senders are
ignored silently.
"""

import datetime as dt
import logging
import os
import tempfile
import zoneinfo

from dotenv import load_dotenv
from pydub import AudioSegment
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import core.db as db
import core.llm as llm
import tools.gmail_tools as gmail_tools
import tools.weather_tools as weather_tools
from core.stt import transcribe
from tools.gmail_tools import GmailAuthError

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID") or "0")

START_MESSAGE = (
    "Hi! I'm your personal assistant. Send me a voice message, an audio file, "
    "or text and I can:\n\n"
    "Manage your Google Calendar — check, add, move, or cancel events. "
    "I can add a Google Meet link when creating meetings.\n\n"
    "Manage your Google Tasks — list, add, complete, or delete tasks.\n\n"
    "Handle your Gmail — read unread mail, search, draft replies, and send email.\n\n"
    "Search your Google Drive and read Docs, Sheets, and PDFs.\n\n"
    "Get travel time and directions via Google Maps.\n\n"
    "Search for nearby restaurants, stores, and businesses.\n\n"
    "Search the web for current news, scores, prices, and business hours.\n\n"
    "Check the weather and forecast for anywhere.\n\n"
    "Answer general questions, with context carried across messages.\n\n"
    "I'll also email you each morning at 5am if rain, snow, fog, or high wind "
    "is in the forecast.\n\n"
    "Use /clear to start a fresh conversation."
)

GENERIC_ERROR = "Something went wrong handling that. Please try again."
STT_ERROR = "Sorry, I couldn't understand that audio. Try again or type your message."

_WET_KEYWORDS = frozenset({
    "drizzle", "rain", "shower", "snow", "sleet", "hail",
    "thunderstorm", "freezing", "fog",
})

# NWS wind thresholds (mph)
_WIND_ADVISORY_MPH = 31
_WIND_ADVISORY_GUST_MPH = 46
_HIGH_WIND_MPH = 40
_HIGH_WIND_GUST_MPH = 58


def _is_wet_weather(condition: str) -> bool:
    c = condition.lower()
    return any(kw in c for kw in _WET_KEYWORDS)


async def rain_alert_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Daily 5am job: email USER_EMAIL if notable weather is forecast for today."""
    user_email = os.getenv("USER_EMAIL")
    if not user_email:
        logger.warning("rain_alert_job: USER_EMAIL not set, skipping")
        return

    try:
        weather = weather_tools.get_weather()
        if "error" in weather:
            logger.error("rain_alert_job: weather fetch failed: %s", weather["error"])
            return

        today = weather.get("today", {})
        condition = today.get("condition", "")
        high = today.get("high", "?")
        low = today.get("low", "?")
        precip_chance = today.get("precip_chance", "unknown")
        location = weather.get("location", os.getenv("USER_LOCATION", "your area"))
        wind_max = today.get("wind_mph_max") or 0
        gust_max = today.get("wind_gust_mph_max") or 0

        wet = _is_wet_weather(condition)
        high_wind = wind_max >= _HIGH_WIND_MPH or gust_max >= _HIGH_WIND_GUST_MPH
        wind_advisory = wind_max >= _WIND_ADVISORY_MPH or gust_max >= _WIND_ADVISORY_GUST_MPH

        if not wet and not wind_advisory:
            return

        # Build alert label for subject + opening line
        alerts = []
        if wet:
            alerts.append(condition)
        if high_wind:
            alerts.append("high wind warning")
        elif wind_advisory:
            alerts.append("wind advisory")
        alert_str = " + ".join(alerts)

        # Fetch hourly breakdown (6am–10pm)
        hourly_lines = []
        hourly_data = weather_tools.get_hourly_forecast()
        if "hours" in hourly_data:
            for h in hourly_data["hours"][6:23]:
                t = h.get("time", "").replace(":00", "")
                temp = h.get("temp", "?")
                cond = h.get("condition", "")
                precip = h.get("precip_chance", "")
                wind = h.get("wind_mph", "?")
                hourly_lines.append(f"  {t:<7} {temp}°F  {cond}  {precip}  {wind} mph")

        # Assemble email
        subject = f"Weather alert: {alert_str} today in {location}"
        body_parts = [
            f"Heads up — {alert_str} is in the forecast for today.\n",
            f"Location: {location}",
            f"High: {high}°F   Low: {low}°F",
            f"Precipitation chance: {precip_chance}",
        ]
        if wind_advisory or high_wind:
            body_parts.append(
                f"Max wind: {wind_max} mph sustained   {gust_max} mph gusts"
            )
        if hourly_lines:
            body_parts.append("\nHourly (6am–10pm):")
            body_parts.extend(hourly_lines)
        body_parts.append("\n— Your assistant")

        gmail_tools.send_email(user_email, subject, "\n".join(body_parts))
        logger.info("rain_alert_job: sent alert to %s (%s)", user_email, alert_str)

    except GmailAuthError:
        logger.error("rain_alert_job: Gmail auth failed — re-run auth_google.py")
    except Exception as exc:
        logger.error("rain_alert_job failed: %s", exc)


def _is_authorized(update: Update) -> bool:
    """Return True only for the single allowed Telegram user."""
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — reply with a capabilities summary."""
    if not _is_authorized(update):
        return
    try:
        await update.message.reply_text(START_MESSAGE)
    except Exception as exc:
        logger.error("start_command failed for user %s: %s", update.effective_user.id, exc)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear — wipe this user's conversation history."""
    if not _is_authorized(update):
        return
    user_id = update.effective_user.id
    try:
        db.clear_history(user_id)
        await update.message.reply_text("Conversation history cleared.")
    except Exception as exc:
        logger.error("clear_command failed for user %s: %s", user_id, exc)
        await update.message.reply_text(GENERIC_ERROR)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a plain text message — send it straight to the LLM."""
    if not _is_authorized(update):
        return
    user_id = update.effective_user.id
    try:
        text = update.message.text or ""
        logger.info("Text message from user %s: %s", user_id, text)
        reply = llm.query(user_id, text)
        await update.message.reply_text(reply)
    except Exception as exc:
        logger.error("handle_text failed for user %s: %s", user_id, exc)
        try:
            await update.message.reply_text(GENERIC_ERROR)
        except Exception:
            pass


def _extract_audio(message) -> object | None:
    """Return the audio-bearing object from a message — a voice note, an audio
    file, or an audio document — or None if the message carries no audio."""
    if message.voice is not None:
        return message.voice
    if message.audio is not None:
        return message.audio
    document = message.document
    if document is not None and (document.mime_type or "").startswith("audio/"):
        return document
    return None


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a voice note or uploaded audio file — download, convert, transcribe,
    then query the LLM. Works for any audio format ffmpeg can decode."""
    if not _is_authorized(update):
        return
    user_id = update.effective_user.id

    placeholder = None
    src_path = None
    mp3_path = None
    try:
        placeholder = await update.message.reply_text("...")

        media = _extract_audio(update.message)
        if media is None:
            await placeholder.edit_text(STT_ERROR)
            return

        # Download the audio to a temp path. The suffix is a hint only — pydub
        # lets ffmpeg sniff the actual format on conversion.
        audio_file = await context.bot.get_file(media.file_id)
        suffix = os.path.splitext(audio_file.file_path or "")[1] or ".ogg"
        tmp_dir = tempfile.gettempdir()
        base = f"audio_{user_id}_{update.message.message_id}"
        src_path = os.path.join(tmp_dir, base + suffix)
        mp3_path = os.path.join(tmp_dir, base + ".mp3")
        await audio_file.download_to_drive(src_path)

        # Convert to MP3 for the transcription API (format auto-detected).
        AudioSegment.from_file(src_path).export(mp3_path, format="mp3")

        # Transcribe.
        try:
            transcript = transcribe(mp3_path)
        except Exception as exc:
            logger.error("Transcription failed for user %s: %s", user_id, exc)
            await placeholder.edit_text(STT_ERROR)
            return

        logger.info("Transcript from user %s: %s", user_id, transcript)

        # Query the LLM and deliver the final reply.
        reply = llm.query(user_id, transcript)
        await placeholder.edit_text(reply)

    except Exception as exc:
        logger.error("handle_audio failed for user %s: %s", user_id, exc)
        try:
            if placeholder is not None:
                await placeholder.edit_text(GENERIC_ERROR)
            else:
                await update.message.reply_text(GENERIC_ERROR)
        except Exception:
            pass
    finally:
        for path in (src_path, mp3_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    logger.warning("Could not remove temp file %s: %s", path, exc)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all error handler so an unhandled exception never crashes the bot."""
    logger.error("Unhandled error: %s", context.error)


def main() -> None:
    """Build the Telegram application and start long polling."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Fill in your .env file.")
    if not ALLOWED_USER_ID:
        raise RuntimeError("ALLOWED_USER_ID is not set. Fill in your .env file.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_audio
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(on_error)

    # Schedule daily rain/snow email alert at 5am in the user's timezone.
    tz_name = os.getenv("USER_TIMEZONE", "America/Chicago")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid USER_TIMEZONE '%s', defaulting to America/Chicago", tz_name)
        tz = zoneinfo.ZoneInfo("America/Chicago")
    application.job_queue.run_daily(rain_alert_job, time=dt.time(5, 0, tzinfo=tz))
    logger.info("Scheduled rain/snow alert at 05:00 %s", tz_name)

    logger.info("Bot starting in polling mode (allowed user: %s)", ALLOWED_USER_ID)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
