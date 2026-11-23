"""Read-only battery, uptime, Wi-Fi, and system information for macOS/Windows."""

import platform
import re
import time

from . import _windows as windows
from ._macos import (
    MacOSPluginError,
    failure,
    finish,
    run_command,
    supported,
    text_value,
)

PLUGIN = {
    "platforms": ["Darwin", "Windows"],
    "name": "mac_system",
    "description": (
        "Read system status without changing anything: battery, uptime, Wi-Fi "
        "network, or general system information on macOS or Windows."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "battery, uptime, wifi, or info (default info).",
            },
        },
        "required": [],
    },
}


def _battery() -> str:
    output = run_command(["/usr/bin/pmset", "-g", "batt"])
    match = re.search(r"(\d+)%", output)
    state = "charging" if "charging" in output.lower() else "not charging"
    return f"Battery is {match.group(1) + '%' if match else 'unknown'}, {state}."


def _windows_battery() -> str:
    try:
        import psutil
        battery = psutil.sensors_battery()
    except ImportError as exc:
        raise windows.WindowsPluginError("Windows battery status needs the psutil package.") from exc
    except Exception as exc:
        raise windows.WindowsPluginError(f"Could not read Windows battery status: {exc}") from exc
    if battery is None:
        return "This device does not report battery information."
    state = "charging" if battery.power_plugged else "not charging"
    return f"Battery is {round(battery.percent)}%, {state}."


def _windows_uptime() -> str:
    try:
        import psutil
        seconds = max(0, int(time.time() - psutil.boot_time()))
    except ImportError as exc:
        raise windows.WindowsPluginError("Windows uptime needs the psutil package.") from exc
    except Exception as exc:
        raise windows.WindowsPluginError(f"Could not read Windows uptime: {exc}") from exc
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours or days:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return "System uptime: " + ", ".join(parts) + "."


def _windows_wifi() -> str:
    output = windows.run_command(["netsh", "wlan", "show", "interfaces"], timeout=10)
    state = re.search(r"^\s*State\s*:\s*(.+?)\s*$", output, re.MULTILINE | re.IGNORECASE)
    if state and state.group(1).casefold() == "disconnected":
        return "Wi-Fi is disconnected."
    for line in output.splitlines():
        match = re.match(r"^\s*SSID\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
        if match and match.group(1) and match.group(1).casefold() != "(none)":
            return f"Connected to Wi-Fi network: {match.group(1)}."
    return "Wi-Fi network information is unavailable (the Windows output may be localized)."


def _windows_info() -> str:
    name = platform.node() or "This device"
    release = platform.release() or "unknown release"
    version = platform.version()
    build_match = re.search(r"\b10\.0\.(\d+)\b", version)
    build = int(build_match.group(1)) if build_match else None
    # Windows 11 reports the NT version 10.0; the build number distinguishes it.
    if release == "10" and build is not None:
        release = "11" if build >= 22000 else "10"
    architecture = platform.machine()
    suffix = f" (build {build})" if build is not None else ""
    arch = f", {architecture}" if architecture else ""
    return f"{name} is running Windows {release}{suffix}{arch}."


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "info").lower()
    if windows.is_windows():
        try:
            if action == "battery":
                result = _windows_battery()
            elif action == "uptime":
                result = _windows_uptime()
            elif action in {"wifi", "wi-fi"}:
                result = _windows_wifi()
            elif action in {"info", "system", "status"}:
                result = _windows_info()
            else:
                return finish(player, "Use system action battery, uptime, wifi, or info.")
            return finish(player, result)
        except windows.WindowsPluginError as exc:
            return finish(player, f"mac_system failed: {exc}")
    if not supported():
        return finish(player, "mac_system is supported on macOS and Windows only.")
    try:
        if action == "battery":
            result = _battery()
        elif action == "uptime":
            result = run_command(["/usr/bin/uptime"]) or "Uptime unavailable."
        elif action in {"wifi", "wi-fi"}:
            result = run_command(["/usr/sbin/networksetup", "-getairportnetwork", "en0"])
            result = result or "Wi-Fi status unavailable."
        elif action in {"info", "system", "status"}:
            product = run_command(["/usr/bin/sw_vers", "-productName"])
            version = run_command(["/usr/bin/sw_vers", "-productVersion"])
            computer = run_command(["/usr/sbin/scutil", "--get", "ComputerName"])
            result = f"{computer}, {product} {version}."
        else:
            return finish(player, "Use system action battery, uptime, wifi, or info.")
        return finish(player, result)
    except MacOSPluginError as exc:
        return failure(player, "mac_system", exc)
