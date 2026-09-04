"""Tests for the self-authoring plugin builder (no network, no LLM calls)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.plugin_loader import PluginRegistry
from core import plugin_builder as pb

SAMPLE_CODE = '''PLUGIN = {
    "name": "hello_tool",
    "description": "Greets the user by name.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"name": {"type": "STRING", "description": "Who to greet"}},
        "required": [],
    },
}

def run(parameters, player=None, session_memory=None):
    name = (parameters or {}).get("name") or "sir"
    return f"Hello, {name}!"
'''


@pytest.fixture
def registry():
    return PluginRegistry({}, lambda msg: None,
                          core_tool_names={"open_app", "shutdown_adhithiya"})


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "USER_PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(pb, "INDEX_PATH", tmp_path / "plugins" / "index.json")
    monkeypatch.setattr(pb, "_api_key", lambda: "test-key")
    pb._DRAFTS.clear()
    return tmp_path


def test_slug_name():
    assert pb._slug_name("My Cool Tool!!") == "my_cool_tool"
    assert pb._slug_name("123abc") == "p_123abc"
    assert pb._slug_name("") == ""


def test_strip_code():
    assert pb._strip_code("```python\nx = 1\n```") == "x = 1"


def test_scan_safe():
    assert pb._scan_source(SAMPLE_CODE) == ""


def test_scan_rejects_dangerous():
    assert pb._scan_source("import subprocess\nPLUGIN={}\ndef run(p): return 'x'")
    assert pb._scan_source("import os\nPLUGIN={}\ndef run(p): os.system('ls')\n")
    assert pb._scan_source("PLUGIN={}\ndef run(p): return eval('1+1')\n")
    assert pb._scan_source("import requests\nPLUGIN={}\ndef run(p): return 'x'\n")
    assert pb._scan_source("import sys\nPLUGIN={}\ndef run(p): return 'x'\n")


def test_full_build_install_run(registry, isolated, monkeypatch):
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: SAMPLE_CODE)

    # draft (no confirm) -> preview, nothing written yet
    out = pb.run({"action": "build", "goal": "greet by name", "name": "hello_tool"}, registry)
    assert "drafted" in out
    assert not registry.has("hello_tool")
    assert not (isolated / "plugins" / "hello_tool.py").exists()

    # confirm -> install + hot-load
    out = pb.run({"action": "build", "goal": "greet by name",
                  "name": "hello_tool", "confirmed": True}, registry)
    assert "Installed" in out
    assert registry.has("hello_tool")
    assert (isolated / "plugins" / "hello_tool.py").exists()

    # it actually runs through the real dispatch path
    assert registry.run("hello_tool", {"name": "Tony"}) == "Hello, Tony!"

    # list
    assert "hello_tool" in pb.run({"action": "list"}, registry)

    # remove requires confirmation
    out = pb.run({"action": "remove", "name": "hello_tool"}, registry)
    assert "Confirm" in out
    out = pb.run({"action": "remove", "name": "hello_tool", "confirmed": True}, registry)
    assert "Removed" in out
    assert not registry.has("hello_tool")
    assert not (isolated / "plugins" / "hello_tool.py").exists()


def test_collision_with_core_tool(registry, isolated, monkeypatch):
    code = SAMPLE_CODE.replace('"hello_tool"', '"open_app"')
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: code)
    out = pb.run({"action": "build", "goal": "whatever", "confirmed": True}, registry)
    assert "built-in" in out


def test_collision_with_existing_plugin(registry, isolated, monkeypatch):
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: SAMPLE_CODE)
    pb.run({"action": "build", "goal": "greet", "name": "hello_tool", "confirmed": True}, registry)
    out = pb.run({"action": "build", "goal": "greet again",
                  "name": "hello_tool", "confirmed": True}, registry)
    assert "already" in out
