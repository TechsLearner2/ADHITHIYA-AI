"""Reminder integration through macOS Reminders or classic Outlook Tasks."""

from datetime import datetime

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
    "name": "mac_reminders",
    "description": (
        "List incomplete reminders or create a reminder in macOS Reminders or "
        "classic Outlook Tasks on Windows. Creating requires confirmed=true. "
        "Windows requires classic Outlook and pywin32."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list or create (default list)."},
            "title": {"type": "STRING", "description": "Reminder text for create."},
            "due": {"type": "STRING", "description": "Optional ISO 8601 due date/time."},
            "list": {"type": "STRING", "description": "Reminders list or Outlook task folder (default Reminders)."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm creating the reminder."},
        },
        "required": [],
    },
}


def _due_literal(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacOSPluginError("Use a due date like 2026-09-01T17:00:00.") from exc
    return f'date {quote_applescript(parsed.strftime("%A, %B %d, %Y at %I:%M:%S %p"))}'


def _outlook_due(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise windows.WindowsPluginError(
            "Use an ISO 8601 due date/time, for example 2026-09-01T17:00:00."
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _run_outlook(parameters: dict, action: str) -> str:
    if action in {"create", "add"}:
        title = text_value(parameters, "title")
        if not title:
            return "Please provide reminder text."
        if not confirmed(parameters):
            return "Please confirm before creating that reminder."
        due_text = text_value(parameters, "due")
        due = _outlook_due(due_text) if due_text else None
    elif action != "list":
        return "Use reminders action list or create."
    else:
        due = None

    _, namespace = windows.outlook_namespace()
    list_name = text_value(parameters, "list", "Reminders")
    folder = windows.outlook_folder(
        namespace, 13, list_name, default_names=("Reminders", "Tasks")
    )
    if action in {"create", "add"}:
        try:
            task = folder.Items.Add()
            task.Subject = title
            if due is not None:
                task.DueDate = due
                task.ReminderTime = due
                task.ReminderSet = True
            task.Save()
        except Exception as exc:
            raise windows.WindowsPluginError(f"Outlook could not save the task: {exc}") from exc
        return f"Created Outlook task: {title}."

    try:
        items = folder.Items
        items.Sort("[DueDate]")
        rows = []
        count = min(int(items.Count), 2000)
        for index in range(1, count + 1):
            task = items.Item(index)
            try:
                is_complete = bool(task.Complete) or int(task.Status) == 2
            except Exception:
                is_complete = False
            if is_complete:
                continue
            title = str(getattr(task, "Subject", "") or "").strip()
            if not title:
                continue
            try:
                due_at = task.DueDate
                due_label = f" — due {due_at.strftime('%Y-%m-%d %H:%M')}" if due_at.year < 4500 else ""
            except Exception:
                due_label = ""
            rows.append(f"{title}{due_label}")
            if len(rows) == 10:
                break
        return "\n".join(rows) if rows else "No incomplete reminders."
    except Exception as exc:
        raise windows.WindowsPluginError(f"Outlook could not list tasks: {exc}") from exc


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "list").lower()
    if windows.is_windows():
        try:
            return finish(player, _run_outlook(parameters, action))
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_reminders failed: {exc}")
    if not supported():
        return finish(player, "mac_reminders is supported on macOS and Windows only.")
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
