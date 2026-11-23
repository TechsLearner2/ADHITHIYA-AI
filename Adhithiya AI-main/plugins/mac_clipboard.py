"""Clipboard read/write through macOS pbpaste/pbcopy or Windows pyperclip."""

from . import _windows as windows
from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    run_command,
    supported,
    text_value,
)

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_clipboard",
    "description": (
        "Get or set the system clipboard on macOS or Windows. Use action 'get' "
        "for reading or 'set' with text; setting requires confirmed=true."
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


def _windows_clipboard(parameters: dict, action: str) -> str:
    try:
        import pyperclip
    except ImportError as exc:
        raise windows.WindowsPluginError("Windows clipboard access needs the pyperclip package.") from exc
    try:
        if action == "get":
            value = pyperclip.paste()
            if not value:
                return "The clipboard is empty."
            if len(value) > 2000:
                value = value[:2000] + "…"
            return f"Clipboard: {value}"
        if action == "set":
            if not confirmed(parameters):
                return "Please confirm before replacing the clipboard."
            if "text" not in parameters or not isinstance(parameters.get("text"), str):
                return "Please provide clipboard text."
            pyperclip.copy(parameters["text"])
            return "Clipboard updated."
        return "Use clipboard action get or set."
    except Exception as exc:
        raise windows.WindowsPluginError(f"Windows clipboard access failed: {exc}") from exc


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "get").lower()
    if windows.is_windows():
        try:
            return finish(player, _windows_clipboard(parameters, action))
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_clipboard failed: {exc}")
    if not supported():
        return finish(player, "mac_clipboard is supported on macOS and Windows only.")
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
