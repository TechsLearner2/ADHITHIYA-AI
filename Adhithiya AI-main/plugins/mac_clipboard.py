"""macOS clipboard read/write through pbpaste and pbcopy."""

from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    run_command,
    supported,
    text_value,
    unsupported,
)

PLUGIN = {
    "name": "mac_clipboard",
    "description": (
        "Get or set the macOS clipboard. Use action 'get' for reading or 'set' "
        "with text; setting requires confirmed=true."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "get or set (default get)."},
            "text": {"type": "STRING", "description": "Clipboard text for set."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm replacing clipboard contents."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_clipboard"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "get").lower()
    try:
        if action == "get":
            value = run_command(["/usr/bin/pbpaste"])
            if not value:
                return finish(player, "The clipboard is empty.")
            if len(value) > 2000:
                value = value[:2000] + "…"
            return finish(player, f"Clipboard: {value}")
        if action == "set":
            if not confirmed(parameters):
                return finish(player, "Please confirm before replacing the clipboard.")
            if "text" not in parameters or not isinstance(parameters.get("text"), str):
                return finish(player, "Please provide clipboard text.")
            run_command(["/usr/bin/pbcopy"], input_text=parameters["text"])
            return finish(player, "Clipboard updated.")
        return finish(player, "Use clipboard action get or set.")
    except MacOSPluginError as exc:
        return failure(player, "mac_clipboard", exc)
