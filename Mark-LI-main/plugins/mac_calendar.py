"""macOS Calendar integration through AppleScript."""

from datetime import datetime

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
    "name": "mac_calendar",
    "description": (
        "List upcoming macOS Calendar events or create an event. Use action "
        "'list' or 'create'; creating requires confirmed=true."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list or create (default list)."},
            "title": {"type": "STRING", "description": "Event title for create."},
            "start": {"type": "STRING", "description": "Start date/time, preferably ISO 8601."},
            "end": {"type": "STRING", "description": "End date/time, preferably ISO 8601."},
            "calendar": {"type": "STRING", "description": "Calendar name (default Calendar)."},
            "notes": {"type": "STRING", "description": "Optional event notes."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm creating the event."},
        },
        "required": [],
    },
}


def _date_literal(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacOSPluginError("Use a date like 2026-09-01T14:00:00.") from exc
    # AppleScript's date parser accepts this unambiguous, English representation.
    return f'date {quote_applescript(parsed.strftime("%A, %B %d, %Y at %I:%M:%S %p"))}'


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_calendar"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "list").lower()
    calendar = text_value(parameters, "calendar", "Calendar")
    try:
        if action in {"create", "add"}:
            title = text_value(parameters, "title")
            start = text_value(parameters, "start")
            if not title or not start:
                return finish(player, "Please provide an event title and start time.")
            if not confirmed(parameters):
                return finish(player, "Please confirm before creating that calendar event.")
            end = text_value(parameters, "end", start)
            script = (
                f"tell application \"Calendar\"\n"
                f"set targetCalendar to calendar {quote_applescript(calendar)}\n"
                f"set newEvent to make new event at end of events of targetCalendar "
                f"with properties {{summary:{quote_applescript(title)}, "
                f"start date:{_date_literal(start)}, end date:{_date_literal(end)}}}\n"
                f"set description of newEvent to {quote_applescript(text_value(parameters, 'notes'))}\n"
                "return summary of newEvent\nend tell"
            )
            result = run_osascript(script) or title
            return finish(player, f"Created calendar event: {result}.")
        if action not in {"list", "today", "upcoming"}:
            return finish(player, "Use calendar action list or create.")
        script = (
            f"tell application \"Calendar\"\n"
            f"set targetCalendar to calendar {quote_applescript(calendar)}\n"
            "set rows to {}\n"
            "repeat with anEvent in (every event of targetCalendar whose start date is greater than or equal to (current date))\n"
            "if (count of rows) is less than 10 then set end of rows to ((summary of anEvent) & \" — \" & ((start date of anEvent) as text))\n"
            "if (count of rows) is 10 then exit repeat\n"
            "end repeat\n"
            "if (count of rows) is 0 then return \"No upcoming events.\"\n"
            "set AppleScript's text item delimiters to linefeed\n"
            "return rows as text\nend tell"
        )
        result = run_osascript(script) or "No upcoming events."
        return finish(player, result)
    except MacOSPluginError as exc:
        return failure(player, "mac_calendar", exc)
