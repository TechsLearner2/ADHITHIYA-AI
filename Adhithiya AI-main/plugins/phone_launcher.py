"""Launch allowlisted apps or system actions on an Infinix Android phone."""

import subprocess

from . import _windows as windows
from ._macos import supported

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "phone_launcher",
    "description": (
        "Launch an allowlisted app or system action on the connected Infinix phone. "
        "macOS uses Soduto; Windows uses Android Debug Bridge (ADB) with USB or "
        "wireless debugging enabled. Provide device_serial if multiple phones are connected."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "target": {
                "type": "STRING",
                "enum": ["youtube", "whatsapp", "camera", "settings", "chrome", "lock_screen", "home_screen"],
                "description": "The target app or system command to execute on the phone."
            },
            "device_serial": {
                "type": "STRING",
                "description": "Optional ADB serial when more than one Android device is connected."
            },
        },
        "required": ["target"]
    }
}

COMMAND_INDEX = {
    "youtube": 0,
    "whatsapp": 1,
    "camera": 2,
    "settings": 3,
    "chrome": 4,
    "lock_screen": 5,
    "home_screen": 6
}

_ANDROID_PACKAGES = {
    "youtube": "com.google.android.youtube",
    "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome",
}

_ANDROID_INTENTS = {
    "camera": ["shell", "am", "start", "-a", "android.media.action.STILL_IMAGE_CAMERA"],
    "settings": ["shell", "am", "start", "-a", "android.settings.SETTINGS"],
    "lock_screen": ["shell", "input", "keyevent", "KEYCODE_SLEEP"],
    "home_screen": ["shell", "input", "keyevent", "KEYCODE_HOME"],
}


def _launch_android(target: str, device_serial: str) -> str:
    if target in _ANDROID_PACKAGES:
        package = _ANDROID_PACKAGES[target]
        command = [
            "shell", "am", "start", "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER", "-p", package,
        ]
    else:
        command = _ANDROID_INTENTS[target]
    output = windows.run_adb(command, serial=device_serial, timeout=20)
    if output.strip():
        return f"ADB requested '{target}' on the connected Android phone.\n{output[:500]}"
    return f"ADB requested '{target}' on the connected Android phone."


def run(target, device_serial=""):
    """Run one preset Soduto menu item or its Windows ADB equivalent."""
    if isinstance(target, dict):
        params = target
        target = params.get("target", "")
        device_serial = params.get("device_serial", device_serial) or ""
    if not isinstance(target, str):
        return f"Target '{target}' is not configured."
    target = target.strip().lower()
    if target not in COMMAND_INDEX:
        return f"Target '{target}' is not configured."

    if windows.is_windows():
        try:
            return _launch_android(target, str(device_serial or "").strip())
        except windows.WindowsPluginError as exc:
            return f"Failed to run phone command: {exc}"
    if not supported():
        return "phone_launcher is supported on macOS and Windows only."

    try:
        down_presses = COMMAND_INDEX[target]
        down_keys = "\n".join(["key code 125\ndelay 0.05" for _ in range(down_presses)])
        applescript = f"""
        tell application "System Events"
            tell process "Soduto"
                perform action "AXPress" of menu bar item 1 of menu bar 1
                delay 0.2
                key code 125
                delay 0.1
                key code 124
                delay 0.1
                repeat 5 times
                    key code 125
                    delay 0.05
                end repeat
                key code 124
                delay 0.1
                {down_keys}
                key code 36
            end tell
        end tell
        """
        subprocess.run(["osascript", "-e", applescript], check=True, timeout=20)
        return f"Successfully executed '{target}' on Infinix HOT 50 5G."
    except Exception as exc:
        return f"Failed to run phone command: {exc}"
