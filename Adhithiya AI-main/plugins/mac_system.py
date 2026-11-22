"""Read-only macOS battery, uptime, Wi-Fi, and system information."""

import re

from ._macos import (
    MacOSPluginError,
    failure,
    finish,
    run_command,
    supported,
    text_value,
    unsupported,
)

PLUGIN = {
    "name": "mac_system",
    "description": (
        "Read macOS system status without changing anything: battery, uptime, "
        "Wi-Fi network, or general system information."
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


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_system"))
    parameters = parameters if isinstance(parameters, dict) else {}
    action = text_value(parameters, "action", "info").lower()
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
