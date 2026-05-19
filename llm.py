"""GPT querying with tool calling for Google Calendar and Google Tasks.

The public entry point is `query(user_id, user_message)`. It loads conversation
history, injects the current datetime into the system prompt, runs a tool-calling
loop against the OpenAI Chat Completions API, persists the exchange, and returns
the final plain-text reply.
"""

import datetime as dt
import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

import calendar_tools
import db
import tasks_tools
from calendar_tools import CalendarAuthError
from tasks_tools import TasksAuthError

load_dotenv()

logger = logging.getLogger("llm")

LLM_MODEL = "gpt-5.4-mini"
HISTORY_LIMIT = 20
MAX_TOOL_ROUNDS = 6

# User-facing error messages.
CALENDAR_AUTH_MESSAGE = (
    "I can't access your calendar right now. Please run python auth_google.py "
    "to re-authenticate."
)
TASKS_AUTH_MESSAGE = (
    "I can't access your tasks right now. Please run python auth_google.py "
    "to re-authenticate."
)
OPENAI_ERROR_MESSAGE = "Something went wrong on my end. Please try again in a moment."

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily create the OpenAI client so the API key is read after .env loads."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


SYSTEM_PROMPT_TEMPLATE = """You are a personal assistant. Be concise and direct.
This is a chat interface so reply in plain sentences — no markdown, no bullet points, no bold text.
Keep replies short unless detail is genuinely needed.

Today is {day_of_week}, {date} at {time} ({timezone}).

You have access to the user's Google Calendar and Google Tasks.
When they ask you to add, change, delete or check calendar events or tasks, use the appropriate tools.
After completing a tool action, confirm in plain language what you did.
When interpreting relative dates like "Tuesday", "next week", "tomorrow" — resolve them from today's date above."""


def _system_prompt() -> str:
    """Build the system prompt with the current local datetime substituted in."""
    now = dt.datetime.now().astimezone()
    return SYSTEM_PROMPT_TEMPLATE.format(
        day_of_week=now.strftime("%A"),
        date=now.strftime("%B %-d, %Y"),
        time=now.strftime("%-I:%M %p"),
        timezone=now.strftime("%Z") or "local time",
    )


# --- Tool schemas exposed to GPT -------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List calendar events in a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "ISO 8601 date string"},
                    "end_date": {"type": "string", "description": "ISO 8601 date string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_datetime": {"type": "string", "description": "ISO 8601 datetime"},
                    "end_datetime": {"type": "string", "description": "ISO 8601 datetime"},
                    "description": {"type": "string", "description": "Optional event description"},
                },
                "required": ["title", "start_datetime", "end_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Update an existing calendar event by event ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string", "description": "Optional new title"},
                    "start_datetime": {"type": "string", "description": "Optional ISO 8601 datetime"},
                    "end_datetime": {"type": "string", "description": "Optional ISO 8601 datetime"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Delete a calendar event by event ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_task_lists",
            "description": "List all available Google Task lists.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks in a task list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_list_id": {
                        "type": "string",
                        "description": "Task list ID — use @default if not specified",
                    },
                    "show_completed": {
                        "type": "boolean",
                        "description": "Whether to include completed tasks (default false)",
                    },
                },
                "required": ["task_list_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "task_list_id": {
                        "type": "string",
                        "description": "Task list ID — use @default if not specified",
                    },
                    "due_date": {"type": "string", "description": "Optional ISO 8601 date string"},
                    "notes": {"type": "string", "description": "Optional task notes"},
                },
                "required": ["title", "task_list_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "task_list_id": {"type": "string"},
                },
                "required": ["task_id", "task_list_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "task_list_id": {"type": "string"},
                },
                "required": ["task_id", "task_list_id"],
            },
        },
    },
]


def _execute_tool(name: str, args: dict):
    """Dispatch a single tool call to the matching Calendar/Tasks function.

    Auth errors are allowed to propagate so the caller can short-circuit with a
    clear user-facing message. Other errors are returned as a result payload so
    GPT can relay them gracefully.
    """
    if name == "list_events":
        return calendar_tools.list_events(args["start_date"], args["end_date"])
    if name == "create_event":
        return calendar_tools.create_event(
            args["title"],
            args["start_datetime"],
            args["end_datetime"],
            args.get("description", ""),
        )
    if name == "update_event":
        return calendar_tools.update_event(
            args["event_id"],
            args.get("title"),
            args.get("start_datetime"),
            args.get("end_datetime"),
        )
    if name == "delete_event":
        return calendar_tools.delete_event(args["event_id"])
    if name == "list_task_lists":
        return tasks_tools.list_task_lists()
    if name == "list_tasks":
        return tasks_tools.list_tasks(
            args.get("task_list_id", "@default"),
            args.get("show_completed", False),
        )
    if name == "create_task":
        return tasks_tools.create_task(
            args["title"],
            args.get("task_list_id", "@default"),
            args.get("due_date"),
            args.get("notes"),
        )
    if name == "complete_task":
        return tasks_tools.complete_task(args["task_id"], args["task_list_id"])
    if name == "delete_task":
        return tasks_tools.delete_task(args["task_id"], args["task_list_id"])

    logger.error("Unknown tool call from GPT: %s", name)
    return {"error": f"Unknown tool '{name}'"}


def query(user_id: int, user_message: str) -> str:
    """Send a user message to GPT (with tool calling) and return the reply text."""
    history = db.get_history(user_id, HISTORY_LIMIT)

    messages: list[dict] = [{"role": "system", "content": _system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    client = _get_client()

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOLS,
            )
            choice = response.choices[0].message

            if not choice.tool_calls:
                reply = (choice.content or "").strip() or "Done."
                db.add_message(user_id, "user", user_message)
                db.add_message(user_id, "assistant", reply)
                db.trim_history(user_id, HISTORY_LIMIT)
                return reply

            # Record the assistant's tool-call turn, then run each tool.
            messages.append({
                "role": "assistant",
                "content": choice.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.tool_calls
                ],
            })

            for tool_call in choice.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                try:
                    result = _execute_tool(name, args)
                except (CalendarAuthError, TasksAuthError):
                    raise
                except Exception as exc:
                    logger.error("Tool '%s' failed: %s", name, exc)
                    result = {"error": str(exc)}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                })

        # Exhausted the tool loop without a final answer.
        logger.error("Tool loop exceeded %d rounds for user %s", MAX_TOOL_ROUNDS, user_id)
        return "I got stuck working on that. Please try rephrasing your request."

    except CalendarAuthError as exc:
        logger.error("Calendar auth error for user %s: %s", user_id, exc)
        return CALENDAR_AUTH_MESSAGE
    except TasksAuthError as exc:
        logger.error("Tasks auth error for user %s: %s", user_id, exc)
        return TASKS_AUTH_MESSAGE
    except Exception as exc:
        logger.error("OpenAI query failed for user %s: %s", user_id, exc)
        return OPENAI_ERROR_MESSAGE
