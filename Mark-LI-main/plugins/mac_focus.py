"""Best-effort macOS Focus/Do Not Disturb toggle via System Events."""

from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    run_osascript,
    supported,
    text_value,
    unsupported,
)

PLUGIN = {
    "name": "mac_focus",
    "description": (
        "Toggle the macOS Focus menu (including Do Not Disturb) through the "
        "Control Center. Requires confirmed=true and Accessibility permission."
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
    if not supported():
        return finish(player, unsupported("mac_focus"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "toggle").lower()
    if action != "toggle":
        return finish(player, "Use focus action toggle.")
    if not confirmed(parameters):
        return finish(player, "Please confirm before toggling Focus.")
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
