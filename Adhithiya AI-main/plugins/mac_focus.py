"""Best-effort macOS Focus or Windows Focus Assist / Do not disturb toggle."""

from . import _windows as windows
from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    run_osascript,
    supported,
    text_value,
)

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_focus",
    "description": (
        "Toggle macOS Focus through Control Center or Windows Focus Assist / Do not "
        "disturb through Quick Settings UI automation. Requires confirmed=true; "
        "Windows requires pywinauto and may depend on the Windows UI version."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "toggle (default toggle)."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm toggling Focus."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "toggle").lower()
    if action != "toggle":
        return finish(player, "Use focus action toggle.")
    if not confirmed(parameters):
        return finish(player, "Please confirm before toggling Focus.")
    if windows.is_windows():
        try:
            windows.toggle_focus_assist()
            return finish(player, "Toggled Windows Focus Assist / Do not disturb.")
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_focus failed: {exc}")
    if not supported():
        return finish(player, "mac_focus is supported on macOS and Windows only.")
    script = (
        'tell application "System Events"\n'
        'tell process "ControlCenter"\n'
        'click menu bar item "Focus" of menu bar 1\n'
        'delay 0.3\n'
        'if exists menu item "Do Not Disturb" of menu 1 of menu bar item "Focus" of menu bar 1 then '
        'click menu item "Do Not Disturb" of menu 1 of menu bar item "Focus" of menu bar 1\n'
        'end tell\nend tell'
    )
    try:
        run_osascript(script)
        return finish(player, "Toggled macOS Focus.")
    except MacOSPluginError as exc:
        return failure(player, "mac_focus", exc)
