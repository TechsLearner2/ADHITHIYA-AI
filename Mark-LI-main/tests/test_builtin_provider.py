"""Tests for the built-in offline brain (provider='builtin'). No network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import builtin_brain as bb
from core import llm


# ── provider-layer routing (core.llm) ────────────────────────────────────────

def test_builtin_provider_routing(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    assert llm.provider() == "builtin"
    assert llm.chat_model() == bb.BUILTIN_MODEL
    assert llm.get_api_key() == "builtin"       # placeholder, not a secret


def test_builtin_default_still_groq_without_config(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert llm.provider() == "groq"             # nothing in config → groq


def test_builtin_tts_uses_mac_voice(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    monkeypatch.setattr(llm, "_say_tts", lambda text: b"WAVDATA")
    assert llm.tts_wav("hello") == b"WAVDATA"


def test_builtin_stt_uses_local_hybrid(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    monkeypatch.setattr(llm, "_transcribe_local", lambda wav: "heard you")
    assert llm.transcribe_wav(b"wav") == "heard you"


def test_builtin_vision_is_text_only(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    out = llm.chat_with_image("what is this?", b"PNG")
    assert "text-only" in out


def test_builtin_image_generation_unavailable(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    with pytest.raises(RuntimeError):
        llm.generate_image("a cat")


def test_builtin_empty_chat_models_list(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {"provider": "builtin"})
    assert llm._chat_models() == [bb.BUILTIN_MODEL]


# ── platform / profile resolution (core.builtin_brain) ───────────────────────

@pytest.mark.parametrize("os_,machine,expected", [
    ("darwin", "arm64", "macos-arm64"),
    ("darwin", "x86_64", "macos-x64"),
    ("linux", "x86_64", "ubuntu-x64"),
    ("linux", "aarch64", "ubuntu-arm64"),
    ("win32", "amd64", "win-cpu-x64"),
    ("win32", "arm64", "win-cpu-arm64"),
])
def test_platform_asset_mapping(monkeypatch, os_, machine, expected):
    monkeypatch.setattr(sys, "platform", os_)
    monkeypatch.setattr("platform.machine", lambda: machine)
    assert bb.platform_asset() == expected


def test_platform_asset_unknown_os_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    with pytest.raises(RuntimeError):
        bb.platform_asset()


def test_default_profile_is_balanced():
    assert bb.profile_name() == "balanced"
    assert bb.MODEL_PROFILES["balanced"]["url"].endswith(".gguf")


def test_model_url_custom_override(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})  # unrelated
    from memory import config_manager as cm
    monkeypatch.setattr(cm, "load_api_keys",
                        lambda: {"builtin_model_url": "https://x/y-model.gguf"})
    url, fname = bb.model_url()
    assert url == "https://x/y-model.gguf"
    assert fname == "y-model.gguf"


# ── install/server state machine (never touches the network) ─────────────────

def test_ensure_server_raises_actionable_error_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("ADHITHIYA_BRAIN_DIR", str(tmp_path / "brain"))
    with pytest.raises(RuntimeError) as ei:
        bb.ensure_server()
    assert "isn't installed yet" in str(ei.value)


def test_status_shape_without_install(monkeypatch, tmp_path):
    monkeypatch.setenv("ADHITHIYA_BRAIN_DIR", str(tmp_path / "brain"))
    st = bb.status()
    assert st["engine"] is False
    assert st["model"] is None
    assert st["port"] == bb.BUILTIN_PORT
    assert st["installing"] is False


def test_unknown_profile_raises():
    with pytest.raises(RuntimeError):
        bb.install_model("not-a-profile")


# ── config persistence (no key stored for no-key providers) ──────────────────

def test_save_api_keys_builtin_stores_no_key(monkeypatch, tmp_path):
    from memory import config_manager as cm
    cfg_file = tmp_path / "api_keys.json"
    cfg_file.write_text("{}")
    monkeypatch.setattr(cm, "CONFIG_FILE", cfg_file)
    cm.save_api_keys("", "builtin")
    import json
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data.get("provider") == "builtin"
    assert "groq_api_key" not in data
    assert "openai_api_key" not in data
