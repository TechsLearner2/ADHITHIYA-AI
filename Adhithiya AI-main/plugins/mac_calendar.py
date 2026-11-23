"""Calendar integration through macOS Calendar or classic Outlook on Windows."""

from datetime import datetime, timedelta

from . import _windows as windows
from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    quote_applescript,
    run_osascript,
    supported,
    text_value,
)

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_calendar",
    "description": (
        "List upcoming calendar events or create an event in macOS Calendar or "
        "classic Outlook on Windows. Use action 'list' or 'create'; creating "
        "requires confirmed=true. Windows requires classic Outlook and pywin32."
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
    return f'date {quote_applescript(parsed.strftime("%A, %B %d, %Y at %I:%M:%S %p"))}'


def _outlook_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise windows.WindowsPluginError(
            f"Use an ISO 8601 {field} date/time, for example 2026-09-01T14:00:00."
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _outlook_folder(namespace, name: str):
    return windows.outlook_folder(namespace, 9, name, default_names=("Calendar",))


def _run_outlook(parameters: dict, action: str) -> str:
    if action in {"create", "add"}:
        title = text_value(parameters, "title")
        start_text = text_value(parameters, "start")
        if not title or not start_text:
            return "Please provide an event title and start time."
        if not confirmed(parameters):
            return "Please confirm before creating that calendar event."
        start = _outlook_datetime(start_text, "start")
        end_text = text_value(parameters, "end")
        end = _outlook_datetime(end_text, "end") if end_text else start + timedelta(minutes=30)
        if end < start:
            return "The event end time must not be before its start time."
        if end == start:
            end = start + timedelta(minutes=30)
    elif action not in {"list", "today", "upcoming"}:
        return "Use calendar action list or create."
    app, namespace = windows.outlook_namespace()
    calendar = text_value(parameters, "calendar", "Calendar")
    folder = _outlook_folder(namespace, calendar)
    if action in {"create", "add"}:
        try:
            event = folder.Items.Add()
            event.Subject = title
            event.Start = start
            event.End = end
            notes = text_value(parameters, "notes")
            if notes:
                event.Body = notes
            event.Save()
        except Exception as exc:
            raise windows.WindowsPluginError(f"Outlook could not save the event: {exc}") from exc
        return f"Created Outlook calendar event: {title}."

    try:
        items = folder.Items
        items.Sort("[Start]")
        try:
            items.IncludeRecurrences = True
        except Exception:
            pass
        # Avoid Outlook's locale-sensitive Restrict date syntax; scan sorted
        # entries with a fixed bound and report if that bound was reached.
        total = int(items.Count)
        scan_count = min(total, 10000)
        rows = []
        now = datetime.now()
        for index in range(1, scan_count + 1):
            event = items.Item(index)
            start = event.Start
            if start < now:
                continue
            title = str(getattr(event, "Subject", "") or "(No title)").strip()
            rows.append(f"{title} — {start.strftime('%Y-%m-%d %H:%M')}")
            if len(rows) == 10:
                break
        if rows:
            return "\n".join(rows)
        if total > scan_count:
            return "No upcoming events found in the first 10,000 Outlook entries; more entries were not scanned."
        return "No upcoming events."
    except Exception as exc:
        raise windows.WindowsPluginError(f"Outlook could not list calendar events: {exc}") from exc


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "list").lower()
    if windows.is_windows():
        try:
            return finish(player, _run_outlook(parameters, action))
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_calendar failed: {exc}")
    if not supported():
        return finish(player, "mac_calendar is supported on macOS and Windows only.")
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
