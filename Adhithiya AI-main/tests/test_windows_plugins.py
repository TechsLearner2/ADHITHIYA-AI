"""Mocked Windows-backend coverage for the macOS/Windows shared plugins."""

import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plugins import (  # noqa: E402
    _windows,
    mac_calendar,
    mac_clipboard,
    mac_focus,
    mac_media,
    mac_notes,
    mac_reminders,
    mac_screenshot,
    mac_system,
    my_custom_tool,
    phone_launcher,
    soduto_control,
)


def use_windows(monkeypatch):
    monkeypatch.setattr(_windows.platform, "system", lambda: "Windows")


def test_shared_plugins_advertise_windows_support():
    plugins = (
        mac_calendar, mac_clipboard, mac_focus, mac_media, mac_notes,
        mac_reminders, mac_screenshot, mac_system, my_custom_tool,
        phone_launcher, soduto_control,
    )
    for module in plugins:
        assert "Windows" in module.PLUGIN["platforms"]


def test_windows_calendar_create_requires_confirmation_before_outlook(monkeypatch):
    use_windows(monkeypatch)
    monkeypatch.setattr(
        _windows, "outlook_namespace",
        lambda: pytest.fail("Outlook must not be opened before confirmation"),
    )

    result = mac_calendar.run({
        "action": "create", "title": "Exam", "start": "2026-12-01T09:00:00",
    })

    assert "confirm" in result.lower()


def test_windows_calendar_create_uses_confirmed_outlook_folder(monkeypatch):
    use_windows(monkeypatch)

    class Event:
        def Save(self):
            self.saved = True

    event = Event()

    class Items:
        def Add(self):
            return event

    folder = types.SimpleNamespace(Items=Items())

    class Namespace:
        def GetDefaultFolder(self, folder_id):
            assert folder_id == 9
            return folder

    monkeypatch.setattr(_windows, "outlook_namespace", lambda: (object(), Namespace()))
    result = mac_calendar.run({
        "action": "create", "title": "Exam", "start": "2026-12-01T09:00:00",
        "confirmed": True, "notes": "Bring calculator.",
    })

    assert result == "Created Outlook calendar event: Exam."
    assert event.Subject == "Exam"
    assert event.Start == datetime(2026, 12, 1, 9, 0)
    assert event.End == datetime(2026, 12, 1, 9, 30)
    assert event.Body == "Bring calculator."
    assert event.saved is True


def test_windows_calendar_lists_only_upcoming_outlook_events(monkeypatch):
    use_windows(monkeypatch)
    now = datetime.now()

    class Event:
        def __init__(self, title, start):
            self.Subject = title
            self.Start = start

    class Items:
        def __init__(self):
            self.entries = [
                Event("Past", now - timedelta(days=1)),
                Event("Future", now + timedelta(days=1)),
            ]
            self.Count = len(self.entries)

        def Sort(self, field):
            assert field == "[Start]"

        def Item(self, index):
            return self.entries[index - 1]

    folder = types.SimpleNamespace(Items=Items())

    class Namespace:
        def GetDefaultFolder(self, folder_id):
            assert folder_id == 9
            return folder

    monkeypatch.setattr(_windows, "outlook_namespace", lambda: (object(), Namespace()))

    result = mac_calendar.run({"action": "list"})

    assert "Future — " in result
    assert "Past" not in result


def test_windows_reminder_create_uses_outlook_task_folder(monkeypatch):
    use_windows(monkeypatch)

    class Task:
        def Save(self):
            self.saved = True

    task = Task()

    class Items:
        def Add(self):
            return task

    folder = types.SimpleNamespace(Items=Items())

    class Namespace:
        def GetDefaultFolder(self, folder_id):
            assert folder_id == 13
            return folder

    monkeypatch.setattr(_windows, "outlook_namespace", lambda: (object(), Namespace()))
    result = mac_reminders.run({
        "action": "create", "title": "Submit assignment",
        "due": "2026-12-03T17:30:00", "confirmed": True,
    })

    assert result == "Created Outlook task: Submit assignment."
    assert task.Subject == "Submit assignment"
    assert task.DueDate == datetime(2026, 12, 3, 17, 30)
    assert task.ReminderTime == datetime(2026, 12, 3, 17, 30)
    assert task.ReminderSet is True
    assert task.saved is True


def test_windows_reminders_list_skips_completed_outlook_tasks(monkeypatch):
    use_windows(monkeypatch)
    due = datetime(2026, 12, 4, 12)

    class Task:
        def __init__(self, title, complete):
            self.Subject = title
            self.Complete = complete
            self.Status = 2 if complete else 0
            self.DueDate = due

    class Items:
        def __init__(self):
            self.entries = [Task("Done", True), Task("Pending", False)]
            self.Count = len(self.entries)

        def Sort(self, field):
            assert field == "[DueDate]"

        def Item(self, index):
            return self.entries[index - 1]

    folder = types.SimpleNamespace(Items=Items())

    class Namespace:
        def GetDefaultFolder(self, folder_id):
            assert folder_id == 13
            return folder

    monkeypatch.setattr(_windows, "outlook_namespace", lambda: (object(), Namespace()))

    result = mac_reminders.run({"action": "list"})

    assert result == "Pending — due 2026-12-04 12:00"


def test_windows_notes_require_confirmation_and_write_outlook_note(monkeypatch):
    use_windows(monkeypatch)
    monkeypatch.setattr(
        _windows, "outlook_namespace",
        lambda: pytest.fail("Outlook must not be opened before confirmation"),
    )
    assert "confirm" in mac_notes.run({"action": "create", "title": "Idea"}).lower()

    class Note:
        def Save(self):
            self.saved = True

    note = Note()

    class Items:
        def Add(self):
            return note

    folder = types.SimpleNamespace(Items=Items())

    class Namespace:
        def GetDefaultFolder(self, folder_id):
            assert folder_id == 10
            return folder

    monkeypatch.setattr(_windows, "outlook_namespace", lambda: (object(), Namespace()))
    result = mac_notes.run({
        "action": "create", "title": "Idea", "body": "Build a Windows backend.",
        "confirmed": True,
    })
    assert result == "Created Outlook note: Idea."
    assert note.Body == "Idea\r\nBuild a Windows backend."
    assert note.saved is True


def test_windows_clipboard_read_and_confirmed_write(monkeypatch):
    use_windows(monkeypatch)
    clipboard = {"value": "hello"}
    fake_pyperclip = types.SimpleNamespace(
        paste=lambda: clipboard["value"],
        copy=lambda value: clipboard.__setitem__("value", value),
    )
    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip)

    assert mac_clipboard.run({"action": "get"}) == "Clipboard: hello"
    assert "confirm" in mac_clipboard.run({"action": "set", "text": "new"}).lower()
    assert clipboard["value"] == "hello"
    assert mac_clipboard.run({"action": "set", "text": "new", "confirmed": True}) == "Clipboard updated."
    assert clipboard["value"] == "new"


def test_windows_focus_keeps_confirmation_gate(monkeypatch):
    use_windows(monkeypatch)
    calls = []
    monkeypatch.setattr(_windows, "toggle_focus_assist", lambda: calls.append("toggle"))

    assert "confirm" in mac_focus.run({"action": "toggle"}).lower()
    assert calls == []
    assert mac_focus.run({"action": "toggle", "confirmed": True}) == "Toggled Windows Focus Assist / Do not disturb."
    assert calls == ["toggle"]


def test_windows_media_uses_media_keys_and_confirmed_volume(monkeypatch):
    use_windows(monkeypatch)
    keys = []
    volumes = []
    monkeypatch.setattr(_windows, "send_media_key", keys.append)
    monkeypatch.setattr(_windows, "set_master_volume", volumes.append)

    assert "confirm" in mac_media.run({"action": "next"}).lower()
    assert keys == []
    assert mac_media.run({"action": "next", "confirmed": True}) == "Skipped to the next track."
    assert keys == [0xB0]
    assert mac_media.run({"action": "play", "confirmed": True}) == "Toggled play/pause on the active Windows media session."
    assert keys[-1] == 0xB3
    assert "confirm" in mac_media.run({"action": "volume", "volume": 45}).lower()
    assert mac_media.run({"action": "volume", "volume": 45, "confirmed": True}) == "Set Windows output volume to 45 percent."
    assert volumes == [45]


def test_windows_screenshot_requires_confirmation_and_saves_on_desktop(monkeypatch, tmp_path):
    use_windows(monkeypatch)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(mac_screenshot, "_windows_screenshot", lambda path: path.write_bytes(b"png"))

    assert "confirm" in mac_screenshot.run({}).lower()
    result = mac_screenshot.run({"confirmed": True})
    assert result.startswith("Saved screenshot to Desktop as Screenshot-")
    assert len(list(desktop.glob("Screenshot-*.png"))) == 1


def test_windows_system_status_uses_windows_backends(monkeypatch):
    use_windows(monkeypatch)
    monkeypatch.setattr(
        _windows, "run_command",
        lambda command, **kwargs: "    State : connected\n    SSID : Home-WiFi\n    BSSID : 01:02:03:04:05:06",
    )
    assert mac_system.run({"action": "wifi"}) == "Connected to Wi-Fi network: Home-WiFi."
    assert "Windows" in mac_system.run({"action": "info"})


def test_windows_system_control_uses_allowlisted_settings_and_volume(monkeypatch):
    use_windows(monkeypatch)
    calls = []
    monkeypatch.setattr(_windows, "open_settings", calls.append)
    monkeypatch.setattr(_windows, "set_master_volume", calls.append)

    assert my_custom_tool.run("set_volume", 120) == "System volume set to 100%."
    assert calls[-1] == 100
    assert my_custom_tool.run("open_setting_pane", setting_pane="bluetooth") == "Opened the Windows bluetooth settings page."
    assert calls[-1] == "ms-settings:bluetooth"
    assert "Choose a settings pane" in my_custom_tool.run("open_setting_pane", setting_pane="unknown")


def test_windows_phone_launcher_uses_allowlisted_adb_commands(monkeypatch):
    use_windows(monkeypatch)
    calls = []
    monkeypatch.setattr(
        _windows, "run_adb",
        lambda command, **kwargs: calls.append((command, kwargs)) or "Starting: Intent",
    )

    result = phone_launcher.run({"target": "youtube", "device_serial": "abc123"})

    assert "requested 'youtube'" in result
    assert calls[0][0][-2:] == ["-p", "com.google.android.youtube"]
    assert calls[0][1]["serial"] == "abc123"


def test_windows_soduto_file_send_is_confirmed_and_sms_is_not_claimed_sent(monkeypatch, tmp_path):
    use_windows(monkeypatch)
    source = tmp_path / "private report.txt"
    source.write_text("contents", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        _windows, "run_adb",
        lambda command, **kwargs: calls.append((command, kwargs)) or "1 file pushed",
    )

    preview = soduto_control.run({"action": "send_files", "file_path": str(source)})
    assert "Confirm sending" in preview
    assert calls == []

    sent = soduto_control.run({
        "action": "send_files", "file_path": str(source), "confirmed": True,
    })
    assert "Sent 'private report.txt'" in sent
    assert calls[0][0][-1] == "/sdcard/Download/private_report.txt"

    sms = soduto_control.run({"action": "send_sms"})
    assert "did not send an SMS" in sms
    assert calls[-1][0][-4:] == ["-a", "android.intent.action.SENDTO", "-d", "smsto:"]


def test_windows_soduto_reports_unavailable_ring_and_scrcpy_hint(monkeypatch):
    use_windows(monkeypatch)
    ring = soduto_control.run({"action": "ring_phone"})
    assert "cannot trigger" in ring

    monkeypatch.setattr(_windows, "adb_device", lambda serial="": ("adb.exe", "device-1"))
    monkeypatch.setattr("plugins.soduto_control.shutil.which", lambda name: None)
    control = soduto_control.run({"action": "control_device"})
    assert "scrcpy installed" in control


def test_windows_adb_missing_software_is_reported_before_phone_action(monkeypatch):
    use_windows(monkeypatch)
    monkeypatch.setattr(_windows.shutil, "which", lambda _name: None)

    result = phone_launcher.run({"target": "youtube"})

    assert "not installed or not on PATH" in result


def test_windows_adb_device_requires_one_authorized_device(monkeypatch):
    use_windows(monkeypatch)
    monkeypatch.setattr(_windows.shutil, "which", lambda name: "C:/platform-tools/adb.exe")
    monkeypatch.setattr(
        _windows, "run_command",
        lambda command, **kwargs: "List of devices attached\nphone-1\tdevice\nphone-2\tdevice\n",
    )

    with pytest.raises(_windows.WindowsPluginError, match="More than one Android device"):
        _windows.adb_device()
    assert _windows.adb_device("phone-2") == ("C:/platform-tools/adb.exe", "phone-2")
