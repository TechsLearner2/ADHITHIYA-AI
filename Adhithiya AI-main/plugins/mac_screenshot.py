"""Capture a confirmed desktop screenshot to the user's Desktop."""

from datetime import datetime
from pathlib import Path

from . import _windows as windows
from ._macos import (
    MacOSPluginError,
    confirmed,
    failure,
    finish,
    run_command,
    supported,
)

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_screenshot",
    "description": (
        "Capture the macOS or Windows screen to the Desktop with a timestamped PNG. "
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


def _windows_screenshot(path: Path) -> None:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise windows.WindowsPluginError("Windows screenshots need the Pillow package.") from exc
    try:
        image = ImageGrab.grab(all_screens=True)
        image.save(path, format="PNG")
    except Exception as exc:
        raise windows.WindowsPluginError(f"Could not capture the Windows desktop: {exc}") from exc


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    if not confirmed(parameters):
        return finish(player, "Please confirm before taking a screenshot.")
    if windows.is_windows():
        desktop = Path.home() / "Desktop"
        if not desktop.is_dir():
            return finish(player, "The Desktop folder was not found.")
        filename = f"Screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        path = desktop / filename
        try:
            _windows_screenshot(path)
            return finish(player, f"Saved screenshot to Desktop as {filename}.")
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_screenshot failed: {exc}")
    if not supported():
        return finish(player, "mac_screenshot is supported on macOS and Windows only.")
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
