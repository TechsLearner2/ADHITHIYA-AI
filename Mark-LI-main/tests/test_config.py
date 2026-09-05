"""Config-persistence and local-provider regression tests."""

import json
import os

import pytest

from memory import config_manager as cm


def test_load_api_keys_merges_legacy_config(monkeypatch, tmp_path):
    """A key saved before the ~/.adhithiya change must survive; the newer
    file's provider choice must win."""
    primary = tmp_path / "home" / ".adhithiya" / "config" / "api_keys.json"
    primary.parent.mkdir(parents=True)
    primary.write_text(json.dumps(
        {"provider": "groq", "groq_api_key": "gsk_TESTKEY123456789"}))

    legacy = tmp_path / "repo" / "config" / "api_keys.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"provider": "local", "os_system": "mac"}))

    # legacy is the user's most recent edit (newer mtime).
    os.utime(primary, (500, 500))
    os.utime(legacy, (1000, 1000))

    monkeypatch.setattr(cm, "CONFIG_FILE", primary)
    monkeypatch.setattr(cm, "get_base_dir", lambda: tmp_path / "repo")

    data = cm.load_api_keys()
    assert data.get("provider") == "local"          # newest choice wins
    assert data.get("os_system") == "mac"
    assert data.get("groq_api_key") == "gsk_TESTKEY123456789"  # key survives


def test_load_api_keys_primary_only(monkeypatch, tmp_path):
    primary = tmp_path / "c.json"
    primary.write_text(json.dumps({"provider": "local", "os_system": "mac"}))
    monkeypatch.setattr(cm, "CONFIG_FILE", primary)
    monkeypatch.setattr(cm, "get_base_dir", lambda: tmp_path / "nope")
    assert cm.load_api_keys() == {"provider": "local", "os_system": "mac"}


def test_local_unreachable_classification(monkeypatch):
    from core import llm

    class _Timeout(Exception):
        pass

    assert llm._local_unreachable(_Timeout("Request timed out"))
    assert llm._local_unreachable(ConnectionError("Connection refused"))
    assert not llm._local_unreachable(RuntimeError("model not found"))


def test_local_stt_raises_without_any_source(monkeypatch):
    from core import llm
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "faster_whisper":
            raise ImportError("no faster-whisper")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="No speech-to-text available"):
        llm._transcribe_local(b"RIFFfakewav")
