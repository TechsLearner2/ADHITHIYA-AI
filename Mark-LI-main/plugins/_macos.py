"""Small standard-library helpers shared by the macOS plugins."""

from __future__ import annotations

import subprocess
import platform
from typing import Sequence


class MacOSPluginError(RuntimeError):
    """An expected, user-facing macOS integration error."""


def supported() -> bool:
    return platform.system() == "Darwin"


def unsupported(plugin_name: str) -> str:
    return f"{plugin_name} is supported on macOS only."


def log(player, message: str) -> None:
    """Best-effort plugin logging without making logging failures user-visible."""
    if player is None:
        return
    writer = getattr(player, "write_log", None)
    if not callable(writer):
        return
    try:
        writer(f"ADHITHIYA: {message}")
    except (AttributeError, TypeError, RuntimeError, OSError):
        return


def text_value(parameters: dict, key: str, default: str = "") -> str:
    value = parameters.get(key, default)
    return value.strip() if isinstance(value, str) else default


def confirmed(parameters: dict) -> bool:
    return parameters.get("confirmed") is True


def quote_applescript(value: str) -> str:
    """Quote a string literal for an AppleScript source snippet."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def run_osascript(script: str, timeout: float = 15.0) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError as exc:
        raise MacOSPluginError("osascript is not available.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MacOSPluginError("macOS did not respond in time.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "AppleScript failed."
        raise MacOSPluginError(message[:180]) from exc
    return result.stdout.strip()


def run_command(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    timeout: float = 10.0,
    check: bool = True,
) -> str:
    try:
        result = subprocess.run(
            list(command),
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except FileNotFoundError as exc:
        raise MacOSPluginError(f"{command[0]} is not available.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MacOSPluginError(f"{command[0]} did not respond in time.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"{command[0]} failed."
        raise MacOSPluginError(message[:180]) from exc
    return result.stdout.strip()


def finish(player, message: str) -> str:
    log(player, message)
    return message


def failure(player, plugin_name: str, error: MacOSPluginError) -> str:
    message = f"{plugin_name} failed: {error}"
    return finish(player, message)
