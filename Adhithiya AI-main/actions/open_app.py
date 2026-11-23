"""Launch an installed desktop application without fuzzy name matching."""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

_SYSTEM = platform.system()

_WEB_SERVICE_URLS = {
    "netflix": "https://www.netflix.com/",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/",
    "youtube": "https://www.youtube.com/",
    "gmail": "https://mail.google.com/",
    "google drive": "https://drive.google.com/",
    "google docs": "https://docs.google.com/",
    "google calendar": "https://calendar.google.com/",
    "notebooklm": "https://notebooklm.google.com/",
}

# Exact aliases only. Web services intentionally do not appear here: use
# browser_control for sites so they open in the user's normal browser/profile.
_APP_ALIASES: dict[str, dict[str, str | None]] = {
    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "microsoft edge":     {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},
    "safari":             {"Windows": None,                       "Darwin": "Safari",               "Linux": None},
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "Microsoft Teams",       "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": None,                   "Linux": None},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": None,                   "Linux": None},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": None},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": None},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": None},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": None,                       "Darwin": "Finder",               "Linux": None},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Settings",      "Linux": "gnome-control-center"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": None,                   "Linux": None},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": None},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": None},
}


def _normalize(raw: str) -> str:
    """Resolve a whole, exact alias; partial names stay untouched."""
    key = " ".join(str(raw).casefold().strip().split())
    os_map = _APP_ALIASES.get(key)
    if os_map is None:
        return str(raw).strip()
    target = os_map.get(_SYSTEM)
    return target if target else str(raw).strip()


def _spawn(command: list[str]) -> bool:
    """Return true only if a process was started and did not immediately fail."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.15)
        return process.poll() is None or process.returncode == 0
    except Exception as exc:
        print(f"[open_app] Process launch failed: {exc}")
        return False


def _windows_shortcut_roots() -> list[Path]:
    roots = []
    for env_name in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _launch_windows(app_name: str) -> bool:
    # Windows settings pages are URI handlers, not executable names.
    if app_name.casefold().startswith("ms-settings:"):
        try:
            os.startfile(app_name)  # type: ignore[attr-defined]
            return True
        except Exception as exc:
            print(f"[open_app] Windows URI launch failed: {exc}")
            return False

    # Treat this as one exact executable/display name, never as a shell command.
    if shutil.which(app_name):
        return _spawn([app_name])

    # Resolve only an exact Start Menu shortcut name. Do not press Enter on a
    # fuzzy Start Menu search and then report success without observing it.
    wanted = Path(app_name).stem.casefold()
    for root in _windows_shortcut_roots():
        try:
            for shortcut in root.rglob("*.lnk"):
                if shortcut.stem.casefold() == wanted:
                    try:
                        os.startfile(str(shortcut))  # type: ignore[attr-defined]
                        return True
                    except Exception as exc:
                        print(f"[open_app] Shortcut launch failed: {exc}")
                        return False
        except OSError:
            continue
    return False


def _launch_macos(app_name: str) -> bool:
    candidates = [app_name]
    if not app_name.casefold().endswith(".app"):
        candidates.append(f"{app_name}.app")
    for candidate in candidates:
        try:
            result = subprocess.run(
                ["open", "-a", candidate],
                capture_output=True,
                timeout=8,
            )
            if result.returncode == 0:
                return True
        except Exception as exc:
            print(f"[open_app] macOS open failed for {candidate}: {exc}")

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    return _spawn([binary]) if binary else False


def _launch_linux(app_name: str) -> bool:
    # App names are not shell commands; pass one exact executable or desktop ID.
    binary = shutil.which(app_name)
    if binary:
        return _spawn([binary])

    # Some desktop apps have a .desktop entry but no binary on PATH. Ask the
    # desktop launcher by exact app ID and accept only an explicit zero exit.
    launcher = shutil.which("gtk-launch")
    if launcher:
        desktop_ids = dict.fromkeys((
            app_name.strip(),
            app_name.strip().lower().replace(" ", "-"),
            app_name.strip().lower().replace(" ", ""),
        ))
        for desktop_id in desktop_ids:
            try:
                result = subprocess.run(
                    [launcher, desktop_id], capture_output=True, timeout=6
                )
                if result.returncode == 0:
                    return True
            except Exception as exc:
                print(f"[open_app] gtk-launch failed for {desktop_id}: {exc}")
    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin": _launch_macos,
    "Linux": _launch_linux,
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    raw_name = params.get("app_name", "")
    app_name = raw_name.strip() if isinstance(raw_name, str) else ""

    if not app_name:
        return "No application name provided."

    service_key = " ".join(app_name.casefold().split())
    service_url = _WEB_SERVICE_URLS.get(service_key)
    if service_url:
        # A deterministic fallback for common services if the model routed a
        # site to this tool. browser_control still opens the user's normal
        # browser/profile and honors an explicit browser choice.
        try:
            from .browser_control import browser_control
            return browser_control(parameters={
                "action": "go_to",
                "url": service_url,
                "browser": params.get("browser"),
            }, player=player)
        except Exception as exc:
            return f"Could not open {service_key} in the browser: {exc}"

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching exact target: '{app_name}' → '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        launched = launcher(normalized)
        if not launched and normalized.casefold() != app_name.casefold():
            launched = launcher(app_name)
        if launched:
            return (
                f"The operating system accepted the launch request for '{app_name}'. "
                "The app window was not independently verified."
            )
        return (
            f"Could not confirm that '{app_name}' launched. "
            "It may not be installed, or its exact app name may be needed."
        )
    except Exception as exc:
        print(f"[open_app] Error: {exc}")
        return f"Failed to launch '{app_name}': {exc}"
