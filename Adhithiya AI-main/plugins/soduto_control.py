"""Phone integration: Soduto on macOS and bounded ADB actions on Windows."""

import re
import shutil
import subprocess
from pathlib import Path

from . import _windows as windows
from ._macos import confirmed, supported

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "soduto_control",
    "description": (
        "Control an Android phone through Soduto on macOS or ADB on Windows. "
        "Windows supports listing shared storage, confirmed file transfer, opening "
        "the SMS composer, and scrcpy device control; ADB cannot perform Soduto's "
        "ring-phone action. ADB and USB/wireless debugging must be configured."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["ring_phone", "browse_files", "send_files", "send_sms", "control_device"],
                "description": "The target action to trigger on the paired Android phone."
            },
            "file_path": {
                "type": "STRING",
                "description": "Local file path to send to the phone's Downloads folder (send_files)."
            },
            "device_serial": {
                "type": "STRING",
                "description": "Optional ADB serial when more than one Android device is connected."
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": "On Windows, confirm transferring the specified file to the phone."
            },
        },
        "required": ["action"]
    }
}

ACTION_DOWN_PRESSES = {
    "browse_files": 0,
    "send_files": 1,
    "send_sms": 2,
    "ring_phone": 3,
    "control_device": 4
}


def _navigate_soduto(down_count):
    down_keys = "\n".join(["key code 125\ndelay 0.1" for _ in range(down_count)])
    script = f"""
    tell application "System Events"
        tell process "Soduto"
            perform action "AXPress" of menu bar item 1 of menu bar 1
            delay 0.3
            key code 125
            delay 0.2
            key code 124
            delay 0.2
            {down_keys}
            delay 0.1
            key code 36
        end tell
    end tell
    """
    subprocess.run(["osascript", "-e", script], check=True, timeout=20)


def _windows_action(action: str, file_path: str, device_serial: str, is_confirmed: bool) -> str:
    serial = device_serial.strip()
    if action == "browse_files":
        output = windows.run_adb(["shell", "ls", "-la", "/sdcard"], serial=serial, timeout=30)
        if not output:
            return "No shared-storage entries were returned by the phone."
        return "Phone shared storage (/sdcard), top level:\n" + output[:3000]

    if action == "send_files":
        if not file_path.strip():
            return "Please provide the local file_path to send to the phone."
        try:
            source = Path(file_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            return f"Could not open the selected file: {exc}"
        if not source.is_file():
            return "The selected file_path is not a regular file."
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source.name).strip("._") or "file"
        if not is_confirmed:
            return (
                f"Confirm sending '{source.name}' to the phone's Downloads folder "
                "with confirmed=true."
            )
        destination = f"/sdcard/Download/{safe_name}"
        output = windows.run_adb(
            ["push", str(source), destination], serial=serial, timeout=300
        )
        detail = f"\n{output[:700]}" if output else ""
        return f"Sent '{source.name}' to the phone's Downloads folder.{detail}"

    if action == "send_sms":
        windows.run_adb(
            ["shell", "am", "start", "-a", "android.intent.action.SENDTO", "-d", "smsto:"],
            serial=serial,
            timeout=20,
        )
        return "Opened the phone's default SMS composer. Review and send the message on the phone; this action did not send an SMS."

    if action == "control_device":
        _, selected = windows.adb_device(serial)
        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            raise windows.WindowsPluginError(
                "Device control needs scrcpy installed and on PATH. ADB detected the phone."
            )
        windows.launch_detached([scrcpy, "-s", selected])
        return "Started scrcpy for the connected phone."

    if action == "ring_phone":
        return (
            "The Windows ADB backend cannot trigger Soduto's ring-phone feature. "
            "Use a phone-finding service such as Google's Find My Device to ring it."
        )

    return f"Invalid action '{action}'. Supported actions: {list(ACTION_DOWN_PRESSES)}"


def run(action, file_path="", device_serial="", confirmed=False):
    """Execute a preset Soduto action or its Windows ADB counterpart."""
    params = action if isinstance(action, dict) else {}
    if params:
        action = params.get("action", "")
        file_path = params.get("file_path", file_path) or ""
        device_serial = params.get("device_serial", device_serial) or ""
        confirmed = params.get("confirmed", confirmed)
    if not isinstance(action, str):
        return f"Invalid action '{action}'. Supported actions: {list(ACTION_DOWN_PRESSES)}"
    action = action.strip().lower()
    if action not in ACTION_DOWN_PRESSES:
        return f"Invalid action '{action}'. Supported actions: {list(ACTION_DOWN_PRESSES)}"

    if windows.is_windows():
        try:
            return _windows_action(
                action,
                str(file_path or ""),
                str(device_serial or ""),
                confirmed is True,
            )
        except windows.WindowsPluginError as exc:
            return f"Soduto/ADB phone integration failed: {exc}"
    if not supported():
        return "soduto_control is supported on macOS and Windows only."

    try:
        _navigate_soduto(ACTION_DOWN_PRESSES[action])
        return f"Successfully executed '{action}' on Infinix HOT 50 5G."
    except Exception as exc:
        return f"Soduto automation error: {exc}"
