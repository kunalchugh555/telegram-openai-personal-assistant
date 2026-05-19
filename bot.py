"""Main entry point — a private Telegram voice/text assistant bot (polling mode).

Voice messages are transcribed with OpenAI, then both voice and text messages
are answered by GPT with Calendar and Tasks tool calling. Only ALLOWED_USER_ID
may interact with the bot; all other senders are ignored silently.
"""

import logging
import os
import tempfile

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

import db
import llm
from stt import transcribe

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID") or "0")

START_MESSAGE = (
    "Hi! I'm your personal assistant. Send me a voice message or text and I can:\n\n"
    "Manage your Google Calendar — check, add, move, or cancel events.\n"
    "Manage your Google Tasks — list, add, complete, or delete tasks.\n"
    "Answer general questions, with context carried across messages.\n\n"
    "Use /clear to start a fresh conversation."
)

GENERIC_ERROR = "Something went wrong handling that. Please try again."
STT_ERROR = "Sorry, I couldn't understand that audio. Try again or type your message."


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


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a voice message — download, convert, transcribe, then query the LLM."""
    if not _is_authorized(update):
        return
    user_id = update.effective_user.id

    placeholder = None
    ogg_path = None
    mp3_path = None
    try:
        placeholder = await update.message.reply_text("...")

        # Download the OGG voice file to a temp path.
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        tmp_dir = tempfile.gettempdir()
        ogg_path = os.path.join(tmp_dir, f"voice_{user_id}_{update.message.message_id}.ogg")
        mp3_path = os.path.join(tmp_dir, f"voice_{user_id}_{update.message.message_id}.mp3")
        await voice_file.download_to_drive(ogg_path)

        # Convert OGG to MP3 for the transcription API.
        AudioSegment.from_file(ogg_path, format="ogg").export(mp3_path, format="mp3")

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
        logger.error("handle_voice failed for user %s: %s", user_id, exc)
        try:
            if placeholder is not None:
                await placeholder.edit_text(GENERIC_ERROR)
            else:
                await update.message.reply_text(GENERIC_ERROR)
        except Exception:
            pass
    finally:
        for path in (ogg_path, mp3_path):
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
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(on_error)

    logger.info("Bot starting in polling mode (allowed user: %s)", ALLOWED_USER_ID)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
