"""macOS Notes integration through AppleScript."""

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
    "name": "mac_notes",
    "description": (
        "Create or search notes in macOS Notes. Use action 'create' or 'search'; "
        "creating requires confirmed=true."
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


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_notes"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "search").lower()
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
