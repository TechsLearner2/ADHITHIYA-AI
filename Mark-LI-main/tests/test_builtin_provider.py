"""Tests for the built-in offline brain (provider='builtin'). No network."""

import json
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


def test_default_profile_is_balanced(monkeypatch):
    # plenty of cores + RAM, no config → balanced
    monkeypatch.setattr(bb, "_logical_cores", lambda: 16)
    monkeypatch.setattr(bb, "_ram_gb", lambda: 64.0)
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert bb.profile_name() == "balanced"
    assert bb.MODEL_PROFILES["balanced"]["url"].endswith(".gguf")


def test_profile_auto_adapts_to_hardware(monkeypatch):
    # RAM is the hard ceiling; cores only pull down when RAM is also scarce.
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    # the user's real machine: dual-core 2015 Intel MacBook, 16 GB → balanced
    monkeypatch.setattr(bb, "_logical_cores", lambda: 2)
    monkeypatch.setattr(bb, "_ram_gb", lambda: 16.0)
    assert bb.profile_name() == "balanced"
    # dual-core + 8 GB → fast (keeps it usable)
    monkeypatch.setattr(bb, "_ram_gb", lambda: 8.0)
    assert bb.profile_name() == "fast"
    # any machine under 8 GB → tiny
    monkeypatch.setattr(bb, "_ram_gb", lambda: 6.0)
    monkeypatch.setattr(bb, "_logical_cores", lambda: 8)
    assert bb.profile_name() == "tiny"
    # 4-core / 16 GB → balanced
    monkeypatch.setattr(bb, "_ram_gb", lambda: 16.0)
    monkeypatch.setattr(bb, "_logical_cores", lambda: 4)
    assert bb.profile_name() == "balanced"


def test_max_tokens_configurable(monkeypatch):
    monkeypatch.setattr(llm, "_cfg", lambda: {})
    assert bb.max_tokens() == bb.BUILTIN_MAX_TOKENS
    from memory import config_manager as cm
    monkeypatch.setattr(cm, "load_api_keys",
                        lambda: {"builtin_max_tokens": 4096})
    assert bb.max_tokens() == 4096


def test_config_profile_overrides_suggestion(monkeypatch):
    monkeypatch.setattr(bb, "_logical_cores", lambda: 2)      # would pick tiny
    from memory import config_manager as cm
    monkeypatch.setattr(cm, "load_api_keys",
                        lambda: {"builtin_profile": "strong"})
    assert bb.profile_name() == "strong"


# ── engine version floors (macOS compatibility) ─────────────────────────────

@pytest.mark.parametrize("macver,expected", [
    ((12, 7, 6), None),      # Monterey — no tool-capable prebuilt
    ((13, 6, 0), None),
    ((14, 1, 0), None),
    ((14, 2, 0), "b6500"),   # Sonoma 14.2+ → legacy build with tools
    ((15, 4, 0), "b6500"),
    ((15, 5, 0), "b10839"),  # Sequoia 15.5+ → newest build
    ((16, 0, 0), "b10839"),
])
def test_engine_version_floor_per_macos(monkeypatch, macver, expected):
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(bb, "_macos_version", lambda: macver)
    assert bb.engine_version() == expected


def test_engine_version_off_macos_uses_latest(monkeypatch):
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(bb, "_macos_version", lambda: None)
    assert bb.engine_version() == "b10839"


def test_engine_version_config_override_wins(monkeypatch):
    monkeypatch.setattr(bb, "_cfg", lambda: {"builtin_engine_version": "b7777"})
    monkeypatch.setattr(bb, "_macos_version", lambda: (12, 7, 6))
    assert bb.engine_version() == "b7777"


def test_engine_asset_urls_modern_and_legacy(monkeypatch):
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(bb, "_arch", lambda: "x64")
    monkeypatch.setattr(bb, "_macos_version", lambda: (15, 5, 0))
    urls = bb.engine_asset_urls()
    assert urls[0].endswith("llama-b10839-bin-macos-x64.tar.gz")
    assert urls[1].endswith("llama-b10839-bin-macos-x64.zip")


def test_engine_asset_urls_empty_when_unsupported(monkeypatch):
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(bb, "_arch", lambda: "x64")
    monkeypatch.setattr(bb, "_macos_version", lambda: (12, 7, 6))
    assert bb.engine_asset_urls() == []


def test_install_engine_guides_local_build_on_old_macos(monkeypatch, tmp_path):
    monkeypatch.setenv("ADHITHIYA_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(bb, "_macos_version", lambda: (12, 7, 6))
    with pytest.raises(RuntimeError) as ei:
        bb.install_engine()
    msg = str(ei.value)
    assert "core.builtin_brain build" in msg
    assert "(12.7.6)" in msg


def test_build_engine_needs_cmake(monkeypatch, tmp_path):
    monkeypatch.setenv("ADHITHIYA_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setattr(bb.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError) as ei:
        bb.build_engine()
    assert "cmake" in str(ei.value)


def test_build_engine_rejects_bad_tag(monkeypatch, tmp_path):
    monkeypatch.setenv("ADHITHIYA_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setattr(bb.shutil, "which", lambda _: "/usr/bin/cmake")
    with pytest.raises(RuntimeError):
        bb.build_engine(tag="not-a-tag")


# ── automatic bootstrap (the "just run it" path) ────────────────────────────

def test_ensure_cmake_installs_via_pip_when_missing(monkeypatch):
    calls = {"which": 0, "pip": []}

    def fake_which(_):
        calls["which"] += 1
        return None if calls["which"] == 1 else "/usr/bin/cmake"

    def fake_run(cmd, **kw):
        calls["pip"].append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(bb.shutil, "which", fake_which)
    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    bb._ensure_cmake()
    assert any("pip" in c and "cmake" in c for c in calls["pip"])


def test_ensure_cmake_skips_when_present(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pip should not run when cmake exists")

    monkeypatch.setattr(bb.shutil, "which", lambda _: "/usr/bin/cmake")
    monkeypatch.setattr(bb.subprocess, "run", boom)
    bb._ensure_cmake()


def test_bootstrap_downloads_engine_then_model(monkeypatch):
    seen = []
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(bb, "_macos_version", lambda: (15, 5, 0))
    monkeypatch.setattr(bb, "server_binary", lambda: None)
    monkeypatch.setattr(bb, "model_file", lambda: None)
    monkeypatch.setattr(bb, "install_engine",
                        lambda p=None: seen.append("engine") or "/e/server")
    monkeypatch.setattr(bb, "install_model",
                        lambda prof=None, progress=None: seen.append("model") or "/m.gguf")
    monkeypatch.setattr(bb, "ensure_server", lambda: 18771)
    monkeypatch.setattr(bb, "warmup", lambda progress=None: True)
    monkeypatch.setattr(bb, "status", lambda: {"done": True})
    assert bb.bootstrap()["done"] is True
    assert seen == ["engine", "model"]


def test_bootstrap_compiles_engine_on_old_macos(monkeypatch):
    """macOS 12: engine_version() None → compile path (CLT + cmake + build)."""
    seen = []
    monkeypatch.setattr(bb, "_cfg", lambda: {})
    monkeypatch.setattr(bb, "_macos_version", lambda: (12, 7, 6))
    monkeypatch.setattr(bb, "server_binary", lambda: None)
    monkeypatch.setattr(bb, "model_file", lambda: None)
    monkeypatch.setattr(bb, "_ensure_xcode_clt", lambda progress=None: seen.append("clt"))
    monkeypatch.setattr(bb, "_ensure_cmake", lambda progress=None: seen.append("cmake"))
    monkeypatch.setattr(bb, "build_engine",
                        lambda progress=None, tag=None: seen.append("build") or "/e/server")
    monkeypatch.setattr(bb, "install_model",
                        lambda prof=None, progress=None: seen.append("model") or "/m.gguf")
    monkeypatch.setattr(bb, "ensure_server", lambda: 18771)
    monkeypatch.setattr(bb, "warmup", lambda progress=None: True)
    monkeypatch.setattr(bb, "status", lambda: {"done": True})
    bb.bootstrap()
    assert seen == ["clt", "cmake", "build", "model"]


def test_bootstrap_skips_when_installed(monkeypatch):
    seen = []
    import pathlib
    fake = pathlib.Path("/nonexistent/llama-server")
    monkeypatch.setattr(bb, "server_binary", lambda: fake)
    monkeypatch.setattr(bb, "model_file", lambda: fake)
    monkeypatch.setattr(bb, "install_engine", lambda p=None: seen.append("engine"))
    monkeypatch.setattr(bb, "install_model",
                        lambda prof=None, progress=None: seen.append("model"))
    monkeypatch.setattr(bb, "ensure_server", lambda: 18771)
    monkeypatch.setattr(bb, "warmup", lambda progress=None: True)
    monkeypatch.setattr(bb, "status", lambda: {"done": True})
    bb.bootstrap()
    assert seen == []                     # nothing to install → no calls


def test_configure_builtin_writes_provider(monkeypatch, tmp_path):
    from memory import config_manager as cm
    cfg_file = tmp_path / "api_keys.json"
    cfg_file.write_text(json.dumps({"provider": "groq",
                                    "groq_api_key": "gsk-keep"}))
    monkeypatch.setattr(cm, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(sys, "platform", "darwin")
    bb._configure_builtin()
    import json as _json
    data = _json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["provider"] == "builtin"
    assert data["os_system"] == "mac"
    assert data["groq_api_key"] == "gsk-keep"   # existing keys preserved


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
