"""Cross-platform system volume and settings launcher (legacy plugin name)."""

import math
import platform
import subprocess

from . import _windows as windows

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_system_control",
    "description": (
        "Set system output volume or open a sound, display, network, Bluetooth, "
        "or security settings pane on macOS or Windows. Windows volume control "
        "uses pycaw; setting panes are chosen from a fixed allowlist."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["set_volume", "open_setting_pane"],
                "description": "The type of system command to execute."
            },
            "volume_level": {
                "type": "INTEGER",
                "description": "Volume level from 0 to 100 (used when action is 'set_volume')."
            },
            "setting_pane": {
                "type": "STRING",
                "enum": ["sound", "displays", "network", "bluetooth", "security"],
                "description": "Which settings pane to open (used when action is 'open_setting_pane')."
            }
        },
        "required": ["action"]
    }
}

_MAC_PANES = {
    "sound": "Sound.prefPane",
    "displays": "Displays.prefPane",
    "network": "Network.prefPane",
    "bluetooth": "Bluetooth.prefPane",
    "security": "Security.prefPane",
}

_WINDOWS_PANES = {
    "sound": "ms-settings:sound",
    "displays": "ms-settings:display",
    "network": "ms-settings:network-status",
    "bluetooth": "ms-settings:bluetooth",
    "security": "ms-settings:windowsdefender",
}


def _volume(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return max(0, min(100, int(value)))


def run(action, volume_level=None, setting_pane=None):
    """Run one allowlisted system action using the host platform's API."""
    if isinstance(action, dict):
        params = action
        action = params.get("action", "")
        volume_level = params.get("volume_level", volume_level)
        setting_pane = params.get("setting_pane", setting_pane)
    if not isinstance(action, str):
        return "Invalid action provided."
    action = action.strip().lower()

    if windows.is_windows():
        if action == "set_volume":
            volume = _volume(volume_level)
            if volume is None:
                return "Please specify a volume level between 0 and 100."
            try:
                windows.set_master_volume(volume)
                return f"System volume set to {volume}%."
            except windows.WindowsPluginError as exc:
                return f"Failed to set Windows volume: {exc}"
        if action == "open_setting_pane":
            pane = setting_pane.strip().lower() if isinstance(setting_pane, str) else ""
            uri = _WINDOWS_PANES.get(pane)
            if not uri:
                return "Choose a settings pane: sound, displays, network, bluetooth, or security."
            try:
                windows.open_settings(uri)
                return f"Opened the Windows {pane} settings page."
            except windows.WindowsPluginError as exc:
                return f"Failed to open Windows settings: {exc}"
        return "Invalid action provided."

    if platform.system() != "Darwin":
        return "mac_system_control is supported on macOS and Windows only."
    try:
        if action == "set_volume":
            volume = _volume(volume_level)
            if volume is None:
                return "Please specify a volume level between 0 and 100."
            subprocess.run(["osascript", "-e", f"set volume output volume {volume}"], check=True)
            return f"System volume set to {volume}%."
        if action == "open_setting_pane":
            pane = setting_pane.strip().lower() if isinstance(setting_pane, str) else ""
            pane_file = _MAC_PANES.get(pane)
            if not pane_file:
                return "Choose a settings pane: sound, displays, network, bluetooth, or security."
            subprocess.run(
                ["open", f"/System/Library/PreferencePanes/{pane_file}"], check=True
            )
            return f"Opened the {pane} settings pane."
        return "Invalid action provided."
    except Exception as exc:
        return f"Failed to execute system command: {exc}"
