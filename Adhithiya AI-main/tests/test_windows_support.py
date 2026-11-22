"""Windows packaging and native speech regression tests (OS-independent)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import llm


def test_system_speech_routes_to_windows_sapi(monkeypatch):
    monkeypatch.setattr(llm.platform, "system", lambda: "Windows")
    monkeypatch.setattr(llm, "_windows_sapi_tts", lambda text: b"windows-wav")

    assert llm._say_tts("Hello from Windows") == b"windows-wav"


def test_system_speech_routes_to_macos_say(monkeypatch):
    monkeypatch.setattr(llm.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(llm, "_mac_say_tts", lambda text: b"macos-wav")

    assert llm._say_tts("Hello from macOS") == b"macos-wav"


def test_system_speech_rejects_linux_without_native_backend(monkeypatch):
    monkeypatch.setattr(llm.platform, "system", lambda: "Linux")

    with pytest.raises(RuntimeError, match="Windows and macOS"):
        llm._say_tts("Hello")
