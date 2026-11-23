"""Notes integration through macOS Notes or classic Outlook Notes on Windows."""

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
    "name": "mac_notes",
    "description": (
        "Create or search notes in macOS Notes or the Notes folder in classic "
        "Outlook on Windows. Creating requires confirmed=true; Windows requires "
        "classic Outlook and pywin32."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create or search (default search)."},
            "title": {"type": "STRING", "description": "Note title for create."},
            "body": {"type": "STRING", "description": "Note body for create."},
            "query": {"type": "STRING", "description": "Text to find when searching."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm creating the note."},
        },
        "required": [],
    },
}


def _run_outlook(parameters: dict, action: str) -> str:
    if action in {"create", "add"}:
        title = text_value(parameters, "title")
        if not title:
            return "Please provide a note title."
        if not confirmed(parameters):
            return "Please confirm before creating that note."
        body = text_value(parameters, "body")
        note_body = title + ("\r\n" + body if body else "")
    elif action == "search":
        query = text_value(parameters, "query")
        if not query:
            return "Please provide text to search for."
    else:
        return "Use notes action search or create."

    _, namespace = windows.outlook_namespace()
    folder = windows.outlook_folder(namespace, 10, "")
    if action in {"create", "add"}:
        try:
            note = folder.Items.Add()
            note.Body = note_body
            note.Save()
        except Exception as exc:
            raise windows.WindowsPluginError(f"Outlook could not save the note: {exc}") from exc
        return f"Created Outlook note: {title}."

    try:
        items = folder.Items
        matches = []
        count = min(int(items.Count), 5000)
        needle = query.casefold()
        for index in range(1, count + 1):
            note = items.Item(index)
            content = str(getattr(note, "Body", "") or "")
            if needle not in content.casefold():
                continue
            title = next((line.strip() for line in content.splitlines() if line.strip()), "(Untitled note)")
            matches.append(title)
            if len(matches) == 10:
                break
        return "\n".join(matches) if matches else "No matching notes."
    except Exception as exc:
        raise windows.WindowsPluginError(f"Outlook could not search notes: {exc}") from exc


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "search").lower()
    if windows.is_windows():
        try:
            return finish(player, _run_outlook(parameters, action))
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_notes failed: {exc}")
    if not supported():
        return finish(player, "mac_notes is supported on macOS and Windows only.")
    try:
        if action in {"create", "add"}:
            title = text_value(parameters, "title")
            body = text_value(parameters, "body")
            if not title:
                return finish(player, "Please provide a note title.")
            if not confirmed(parameters):
                return finish(player, "Please confirm before creating that note.")
            script = (
                "tell application \"Notes\"\n"
                "set targetAccount to first account\n"
                f"make new note at end of notes of targetAccount with properties "
                f"{{name:{quote_applescript(title)}, body:{quote_applescript(body)}}}\n"
                f"return {quote_applescript(title)}\nend tell"
            )
            result = run_osascript(script) or title
            return finish(player, f"Created note: {result}.")
        if action != "search":
            return finish(player, "Use notes action search or create.")
        query = text_value(parameters, "query")
        if not query:
            return finish(player, "Please provide text to search for.")
        script = (
            "tell application \"Notes\"\n"
            f"set matches to every note whose name contains {quote_applescript(query)} "
            f"or body contains {quote_applescript(query)}\n"
            "if (count of matches) is 0 then return \"No matching notes.\"\n"
            "set rows to {}\n"
            "repeat with aNote in matches\n"
            "if (count of rows) is less than 10 then set end of rows to (name of aNote)\n"
            "if (count of rows) is 10 then exit repeat\n"
            "end repeat\n"
            "set AppleScript's text item delimiters to linefeed\n"
            "return rows as text\nend tell"
        )
        return finish(player, run_osascript(script) or "No matching notes.")
    except MacOSPluginError as exc:
        return failure(player, "mac_notes", exc)
