"""Capture a macOS screenshot to the user's Desktop."""

from datetime import datetime
from pathlib import Path

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
    "name": "mac_screenshot",
    "description": (
        "Capture the macOS screen to the Desktop with a timestamped PNG. "
        "Requires confirmed=true."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "confirmed": {"type": "BOOLEAN", "description": "Confirm taking a screenshot."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_screenshot"))
    parameters = parameters if isinstance(parameters, dict) else {}
    if not confirmed(parameters):
        return finish(player, "Please confirm before taking a screenshot.")
    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        return finish(player, "The Desktop folder was not found.")
    filename = f"Screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    path = desktop / filename
    try:
        run_command(["/usr/sbin/screencapture", "-x", str(path)], timeout=30)
        return finish(player, f"Saved screenshot to Desktop as {filename}.")
    except MacOSPluginError as exc:
        return failure(player, "mac_screenshot", exc)
