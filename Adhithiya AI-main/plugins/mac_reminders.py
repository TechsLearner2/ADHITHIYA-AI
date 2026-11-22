"""macOS Reminders integration through AppleScript."""

from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    quote_applescript,
    run_osascript,
    supported,
    text_value,
    unsupported,
)

PLUGIN = {
    "name": "mac_reminders",
    "description": (
        "List incomplete macOS Reminders or create a reminder. Use action "
        "'list' or 'create'; creating requires confirmed=true."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list or create (default list)."},
            "title": {"type": "STRING", "description": "Reminder text for create."},
            "due": {"type": "STRING", "description": "Optional ISO 8601 due date/time."},
            "list": {"type": "STRING", "description": "Reminders list name (default Reminders)."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm creating the reminder."},
        },
        "required": [],
    },
}


def _due_literal(value: str) -> str:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacOSPluginError("Use a due date like 2026-09-01T17:00:00.") from exc
    return f'date {quote_applescript(parsed.strftime("%A, %B %d, %Y at %I:%M:%S %p"))}'


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_reminders"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "list").lower()
    list_name = text_value(parameters, "list", "Reminders")
    try:
        if action in {"create", "add"}:
            title = text_value(parameters, "title")
            if not title:
                return finish(player, "Please provide reminder text.")
            if not confirmed(parameters):
                return finish(player, "Please confirm before creating that reminder.")
            due = text_value(parameters, "due")
            due_property = f", due date:{_due_literal(due)}" if due else ""
            script = (
                "tell application \"Reminders\"\n"
                f"set targetList to list {quote_applescript(list_name)}\n"
                f"make new reminder at end of reminders of targetList with properties "
                f"{{name:{quote_applescript(title)}{due_property}}}\n"
                f"return {quote_applescript(title)}\nend tell"
            )
            result = run_osascript(script) or title
            return finish(player, f"Created reminder: {result}.")
        if action != "list":
            return finish(player, "Use reminders action list or create.")
        script = (
            "tell application \"Reminders\"\n"
            f"set targetList to list {quote_applescript(list_name)}\n"
            "set rows to {}\n"
            "repeat with aReminder in (every reminder of targetList whose completed is false)\n"
            "if (count of rows) is less than 10 then set end of rows to (name of aReminder)\n"
            "if (count of rows) is 10 then exit repeat\n"
            "end repeat\n"
            "if (count of rows) is 0 then return \"No incomplete reminders.\"\n"
            "set AppleScript's text item delimiters to linefeed\n"
            "return rows as text\nend tell"
        )
        return finish(player, run_osascript(script) or "No incomplete reminders.")
    except MacOSPluginError as exc:
        return failure(player, "mac_reminders", exc)
