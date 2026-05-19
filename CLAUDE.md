# CLAUDE.md — Instructions for Claude Code

## Mandatory workflow for every prompt

### 1. Update project_structure.txt — MANDATORY

**Before starting any prompt:**
Read `project_structure.txt` to understand the current state of the repo.

**After completing any prompt that changes files:**
Update `project_structure.txt` to reflect all changes — new files, removed files,
updated file descriptions, and any new or changed design decisions.

This file is the source of truth for the project. Always keep it accurate.

## Project overview

This is a personal Telegram voice assistant bot. The user sends voice messages,
the bot transcribes them with OpenAI Whisper, queries GPT with tool calling,
and can read/write Google Calendar and Google Tasks. Replies are plain text.

## Git rules

- Never include "Co-Authored-By: Claude" or any Claude attribution in commit messages

## Key rules

- Never hardcode API keys or tokens anywhere. Always use environment variables via .env
- Never commit token.json, .env, assistant.db, or any secret files
- All datetime handling must be timezone-aware
- The bot is private — only the ALLOWED_USER_ID in .env can interact with it
- Keep replies concise and in plain sentences — no markdown formatting in replies
- All Google API calls must handle token expiry gracefully with a clear user-facing error
- SQLite DB and token.json paths must respect the DATA_DIR env var for Fly.io compatibility
- Log all errors to stdout with timestamps
- Every Telegram handler must be wrapped in try/except so a bad message never crashes the bot
