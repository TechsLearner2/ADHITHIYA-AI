"""Lazy helpers for Windows plugin integrations.

Windows-only packages and APIs are imported only when a Windows feature runs,
so plugin discovery and testing remain safe on other operating systems.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from threading import local
from typing import Sequence

_COM_STATE = local()


class WindowsPluginError(RuntimeError):
    """An expected, user-facing Windows integration error."""


def is_windows() -> bool:
    return platform.system() == "Windows"


def run_command(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    timeout: float = 10.0,
    check: bool = True,
) -> str:
    """Run an argument vector (never a shell string) and normalize errors."""
    if not command:
        raise WindowsPluginError("No Windows command was specified.")
    kwargs = {}
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if no_window:
        kwargs["creationflags"] = no_window
    try:
        result = subprocess.run(
            list(command), input=input_text, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=check, **kwargs,
        )
    except FileNotFoundError as exc:
        raise WindowsPluginError(f"{command[0]} is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise WindowsPluginError(f"{command[0]} did not respond in time.") from exc
    except subprocess.CalledProcessError as exc:
        lines = (exc.stderr or exc.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else f"{command[0]} failed."
        raise WindowsPluginError(detail[:220]) from exc
    return (result.stdout or "").strip()


def open_settings(uri: str) -> None:
    """Open a fixed Windows Settings URI chosen by a plugin allowlist."""
    if not is_windows():
        raise WindowsPluginError("Windows Settings are available on Windows only.")
    opener = getattr(os, "startfile", None)
    if not callable(opener):
        raise WindowsPluginError("The Windows Settings launcher is unavailable.")
    try:
        opener(uri)
    except OSError as exc:
        raise WindowsPluginError(f"Could not open Windows Settings: {exc}") from exc


def send_media_key(virtual_key: int) -> None:
    """Send one documented media-key event to the active Windows media session."""
    if not is_windows():
        raise WindowsPluginError("Windows media keys are available on Windows only.")
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, 0x0002, 0)  # KEYEVENTF_KEYUP
    except Exception as exc:
        raise WindowsPluginError(f"Could not send the media key: {exc}") from exc


def set_master_volume(percent: int) -> None:
    """Set the Windows output-device volume using the optional pycaw backend."""
    if not is_windows():
        raise WindowsPluginError("Windows audio controls are available on Windows only.")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 100:
        raise WindowsPluginError("Volume must be a number from 0 to 100.")
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError as exc:
        raise WindowsPluginError(
            "Setting Windows volume needs the optional pycaw and comtypes packages."
        ) from exc
    try:
        device = AudioUtilities.GetSpeakers()
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        endpoint = cast(interface, POINTER(IAudioEndpointVolume))
        endpoint.SetMasterVolumeLevelScalar(float(percent) / 100.0, None)
    except Exception as exc:
        raise WindowsPluginError(f"Could not set Windows output volume: {exc}") from exc


def toggle_focus_assist() -> None:
    """Best-effort UI Automation of the visible Windows Focus/DND quick toggle."""
    if not is_windows():
        raise WindowsPluginError("Windows Focus controls are available on Windows only.")
    try:
        import pyautogui
        from pywinauto import Desktop
    except ImportError as exc:
        raise WindowsPluginError(
            "Windows Focus automation needs pyautogui and pywinauto."
        ) from exc

    try:
        desktop = Desktop(backend="uia")
        # Windows 11 exposes Do not disturb in Notification Center (Win+N);
        # Windows 10 exposes Focus assist in Action Center (Win+A).
        for shortcut in ("n", "a"):
            pyautogui.hotkey("win", shortcut)
            time.sleep(0.6)
            for window in desktop.windows():
                try:
                    controls = window.descendants()
                except Exception:
                    continue
                for control in controls:
                    try:
                        name = str(control.window_text() or "").strip().casefold()
                        kind = str(control.element_info.control_type or "").casefold()
                    except Exception:
                        continue
                    normalized = re.sub(r"[^a-z0-9 ]+", " ", name).strip()
                    is_focus_toggle = (
                        normalized in {
                            "focus assist", "focus assist on", "focus assist off",
                            "do not disturb", "do not disturb on", "do not disturb off",
                            "turn on do not disturb", "turn off do not disturb",
                        }
                        or normalized.startswith("focus assist ")
                        or normalized.startswith("do not disturb ")
                    )
                    if is_focus_toggle and kind in {"button", "checkbox", "togglebutton"}:
                        control.click_input()
                        return
            pyautogui.press("esc")
    except Exception as exc:
        try:
            pyautogui.press("esc")
        except Exception:
            pass
        raise WindowsPluginError(f"Could not toggle Windows Focus: {exc}") from exc

    try:
        pyautogui.press("esc")
    except Exception:
        pass
    raise WindowsPluginError(
        "Could not find a Do not disturb or Focus assist toggle in Windows Quick Settings. "
        "Open Windows Notifications settings and change it manually."
    )


def outlook_namespace():
    """Return (Outlook.Application, MAPI namespace) for classic Outlook COM."""
    if not is_windows():
        raise WindowsPluginError("Outlook integration is available on Windows only.")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise WindowsPluginError(
            "Classic Outlook integration needs pywin32. New Outlook may not expose COM."
        ) from exc
    try:
        if not getattr(_COM_STATE, "initialized", False):
            pythoncom.CoInitialize()
            _COM_STATE.initialized = True
        app = win32com.client.Dispatch("Outlook.Application")
        return app, app.GetNamespace("MAPI")
    except Exception as exc:
        raise WindowsPluginError(
            "Classic Outlook could not be opened. Install and configure classic Outlook first."
        ) from exc


def outlook_folder(namespace, folder_id: int, requested_name: str = "", default_names=()):
    """Resolve a default Outlook folder or a same-store folder by exact name."""
    try:
        default = namespace.GetDefaultFolder(folder_id)
    except Exception as exc:
        raise WindowsPluginError("The requested Outlook folder is unavailable.") from exc
    requested = requested_name.strip().casefold()
    aliases = {str(name).strip().casefold() for name in default_names}
    if not requested or requested in aliases:
        return default
    try:
        folders = default.Parent.Folders
        for folder in folders:
            if str(folder.Name).strip().casefold() == requested:
                return folder
    except Exception:
        pass
    raise WindowsPluginError(f"Outlook folder '{requested_name[:80]}' was not found.")


def adb_device(serial: str = "") -> tuple[str, str]:
    """Resolve exactly one authorized Android device using the local ADB client."""
    adb = shutil.which("adb")
    if not adb:
        raise WindowsPluginError(
            "Android Debug Bridge (adb) is not installed or not on PATH."
        )
    output = run_command([adb, "devices"], timeout=10)
    devices = []
    unauthorized = []
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        if fields[1] == "device":
            devices.append(fields[0])
        elif fields[1] == "unauthorized":
            unauthorized.append(fields[0])
    if serial:
        if serial not in devices:
            if serial in unauthorized:
                raise WindowsPluginError(
                    f"Android device {serial} is not authorized; unlock it and approve USB debugging."
                )
            raise WindowsPluginError(f"Authorized Android device {serial} was not found.")
        return adb, serial
    if len(devices) == 1:
        return adb, devices[0]
    if not devices and unauthorized:
        raise WindowsPluginError(
            "The Android device is connected but not authorized for USB debugging."
        )
    if not devices:
        raise WindowsPluginError("No authorized Android device is connected through ADB.")
    raise WindowsPluginError(
        "More than one Android device is connected; provide its serial number."
    )


def run_adb(arguments: Sequence[str], serial: str = "", timeout: float = 20.0) -> str:
    adb, selected = adb_device(serial)
    output = run_command([adb, "-s", selected, *arguments], timeout=timeout)
    if re.search(
        r"(?im)^\s*(?:error|exception):|^\s*error\s+type|"
        r"no activity found|activity class .* does not exist|permission denial",
        output,
    ):
        raise WindowsPluginError(output.strip().splitlines()[-1][:220])
    return output


def launch_detached(command: Sequence[str]) -> None:
    """Launch an allowlisted GUI helper without blocking the assistant process."""
    if not command:
        raise WindowsPluginError("No Windows application was specified.")
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    if flags:
        kwargs["creationflags"] = flags
    try:
        subprocess.Popen(list(command), **kwargs)
    except FileNotFoundError as exc:
        raise WindowsPluginError(f"{command[0]} is not installed or not on PATH.") from exc
    except OSError as exc:
        raise WindowsPluginError(f"Could not start {command[0]}: {exc}") from exc
