"""Media controls through macOS Music or Windows' active media session."""

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
    "name": "mac_media",
    "description": (
        "Control macOS Music or the active Windows media session: play/pause, "
        "next, previous, or set system output volume. Every change requires "
        "confirmed=true. Windows play and pause both send the system toggle key; "
        "volume changes use pycaw."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play, pause, next, previous, or volume."},
            "volume": {"type": "INTEGER", "description": "Volume from 0 to 100 for action volume."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm the media change."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action").lower().replace("-", "_")
    actions = {
        "play": ("play", "Started playback."),
        "pause": ("pause", "Paused playback."),
        "next": ("next track", "Skipped to the next track."),
        "previous": ("previous track", "Went to the previous track."),
    }
    if action == "volume":
        value = parameters.get("volume")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            return finish(player, "Volume must be a number from 0 to 100.")
        if not confirmed(parameters):
            return finish(player, "Please confirm before changing media volume.")
        if windows.is_windows():
            try:
                windows.set_master_volume(int(value))
                return finish(player, f"Set Windows output volume to {int(value)} percent.")
            except windows.WindowsPluginError as exc:
                return finish(player, f"mac_media failed: {exc}")
        if not supported():
            return finish(player, "mac_media is supported on macOS and Windows only.")
        try:
            run_osascript(f'tell application "Music" to set sound volume to {int(value)}')
            return finish(player, f"Set media volume to {int(value)} percent.")
        except MacOSPluginError as exc:
            return failure(player, "mac_media", exc)

    if action not in actions:
        return finish(player, "Use media action play, pause, next, previous, or volume.")
    if not confirmed(parameters):
        return finish(player, f"Please confirm before I {action} media.")
    if windows.is_windows():
        keys = {"play": 0xB3, "pause": 0xB3, "next": 0xB0, "previous": 0xB1}
        try:
            windows.send_media_key(keys[action])
            message = (
                "Toggled play/pause on the active Windows media session."
                if action in {"play", "pause"}
                else actions[action][1]
            )
            return finish(player, message)
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_media failed: {exc}")
    if not supported():
        return finish(player, "mac_media is supported on macOS and Windows only.")
    command, message = actions[action]
    try:
        run_osascript(f'tell application "Music" to {command}')
        return finish(player, message)
    except MacOSPluginError as exc:
        return failure(player, "mac_media", exc)
