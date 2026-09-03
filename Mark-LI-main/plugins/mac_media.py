"""Basic macOS Music playback controls through AppleScript."""

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
    "name": "mac_media",
    "description": (
        "Control the macOS Music player: play, pause, next, previous, or set "
        "volume. Playback and volume changes require confirmed=true."
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
    if not supported():
        return finish(player, unsupported("mac_media"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action").lower().replace("-", "_")
    actions = {
        "play": ("play", "Started playback."),
        "pause": ("pause", "Paused playback."),
        "next": ("next track", "Skipped to the next track."),
        "previous": ("previous track", "Went to the previous track."),
    }
    try:
        if action == "volume":
            value = parameters.get("volume")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                return finish(player, "Volume must be a number from 0 to 100.")
            if not confirmed(parameters):
                return finish(player, "Please confirm before changing media volume.")
            command = f"set sound volume to {int(value)}"
            message = f"Set media volume to {int(value)} percent."
        elif action in actions:
            if not confirmed(parameters):
                return finish(player, f"Please confirm before I {action} media.")
            command, message = actions[action]
        else:
            return finish(player, "Use media action play, pause, next, previous, or volume.")
        run_osascript(f'tell application "Music" to {command}')
        return finish(player, message)
    except MacOSPluginError as exc:
        return failure(player, "mac_media", exc)
