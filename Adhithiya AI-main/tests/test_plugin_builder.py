"""Tests for the self-authoring plugin builder (no real network/LLM calls)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.plugin_loader import PluginRegistry
from core import plugin_builder as pb

SAMPLE_CODE = '''PLUGIN = {
    "platforms": ["Linux"],
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
    monkeypatch.setattr(pb, "_research_goal", lambda _goal: ([], ""))
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


def test_generated_plugin_must_target_the_detected_os():
    assert pb._validate_draft(SAMPLE_CODE, "Linux").valid

    no_platform = SAMPLE_CODE.replace('    "platforms": ["Linux"],\n', "")
    record = pb._validate_draft(no_platform, "Linux")
    assert not record.valid
    assert "must declare platforms=['Linux']" in record.error

    wrong_platform = SAMPLE_CODE.replace('["Linux"]', '["Darwin"]')
    record = pb._validate_draft(wrong_platform, "Linux")
    assert not record.valid
    assert "Unsupported on Linux" in record.error


def test_scan_rejects_dangerous():
    assert pb._scan_source("import subprocess\nPLUGIN={}\ndef run(p): return 'x'")
    assert pb._scan_source("import os\nPLUGIN={}\ndef run(p): os.system('ls')\n")
    assert pb._scan_source("PLUGIN={}\ndef run(p): return eval('1+1')\n")
    assert pb._scan_source("import requests\nPLUGIN={}\ndef run(p): return 'x'\n")
    assert pb._scan_source("import sys\nPLUGIN={}\ndef run(p): return 'x'\n")


def test_scan_allows_only_approved_live_search_helper():
    code = '''from actions.web_search import search_results
PLUGIN = {"name":"search_tool", "description":"Searches for a topic.",
          "parameters":{"type":"OBJECT", "properties":{}}}
def run(parameters):
    return str(search_results("topic", max_results=2))
'''
    assert pb._scan_source(code) == ""
    assert "only search_results" in pb._scan_source(
        code.replace("import search_results", "import _ddg_search")
    )
    assert "forbidden import" in pb._scan_source(
        code.replace("from actions.web_search import search_results", "import urllib.request")
    )


def test_generated_plugins_may_only_probe_executables_with_shutil_which():
    code = '''from shutil import which
PLUGIN = {"name":"probe_tool", "description":"Checks for a local binary.",
          "parameters":{"type":"OBJECT", "properties":{}}}
def run(parameters):
    if which("ffmpeg") is None:
        return "ffmpeg is not installed."
    return "ffmpeg is available."
'''
    assert pb._scan_source(code) == ""
    assert "only which may be imported from shutil" in pb._scan_source(
        code.replace("from shutil import which", "from shutil import rmtree")
    )
    assert "only which from shutil" in pb._scan_source(
        code.replace("from shutil import which", "import shutil")
    )


def test_scan_rejects_module_level_work_and_placeholder_run():
    module_work = "from actions.web_search import search_results\n" + SAMPLE_CODE.replace(
        "PLUGIN =", "search_results('should not run during import')\nPLUGIN =", 1
    )
    assert "module-level executable" in pb._scan_source(module_work)
    placeholder = SAMPLE_CODE.replace(
        '    name = (parameters or {}).get("name") or "sir"\n'
        '    return f"Hello, {name}!"',
        '    return "TODO: not implemented"',
    )
    assert "placeholder" in pb._scan_source(placeholder)


def test_generator_prompt_includes_live_evidence_as_untrusted_context(monkeypatch):
    seen = {}

    def fake_chat(messages):
        seen["prompt"] = messages[0]["content"]
        return {"text": SAMPLE_CODE}

    from core import llm
    monkeypatch.setattr(llm, "chat", fake_chat)

    result = pb._generate(
        "lookup current weather", "weather_lookup", "test-key",
        research_results=[{
            "title": "Weather API docs",
            "snippet": "The service returns current weather as JSON.",
            "url": "https://docs.example/weather",
        }],
        target_os="Linux",
    )

    assert result == SAMPLE_CODE
    assert "Weather API docs" in seen["prompt"]
    assert "untrusted live search" in seen["prompt"].lower()
    assert "actions.web_search import search_results" in seen["prompt"]
    assert "Do not invent search results" in seen["prompt"]
    assert "Target OS detected by the running app: Linux" in seen["prompt"]
    assert "platforms'] to exactly ['Linux']" in seen["prompt"]
    assert "from shutil" in seen["prompt"]


def test_build_uses_real_search_context_and_reports_sources(
    registry, isolated, monkeypatch,
):
    evidence = [{
        "title": "Official docs",
        "snippet": "Supported method and request format.",
        "url": "https://docs.example/api",
    }]
    passed = []
    monkeypatch.setattr(pb, "_research_goal", lambda goal: (evidence, ""))
    monkeypatch.setattr(
        pb,
        "_generate",
        lambda goal, hint, key, research_results=None, repair_note="":
            passed.extend(research_results or []) or SAMPLE_CODE,
    )

    preview = pb.run({"action": "build", "goal": "use the API"}, registry)

    assert "drafted" in preview
    assert "Live web search returned 1" in preview
    assert "https://docs.example/api" in preview
    assert passed == evidence


def test_invalid_draft_gets_one_repair_attempt(registry, isolated, monkeypatch):
    drafts = iter(["PLUGIN={}\ndef run(parameters): ...", SAMPLE_CODE])
    repairs = []

    def generate(goal, hint, key, research_results=None, repair_note=""):
        repairs.append(repair_note)
        return next(drafts)

    monkeypatch.setattr(pb, "_generate", generate)

    preview = pb.run({"action": "build", "goal": "greet by name"}, registry)

    assert "drafted" in preview
    assert len(repairs) == 2
    assert "placeholder" in repairs[1]


def test_builder_targets_the_detected_windows_host(registry, isolated, monkeypatch):
    monkeypatch.setattr(pb.platform, "system", lambda: "Windows")
    seen = {}
    windows_code = SAMPLE_CODE.replace('["Linux"]', '["Windows"]')

    def generate(goal, hint, key, target_os=None, **kwargs):
        seen["target_os"] = target_os
        return windows_code

    monkeypatch.setattr(pb, "_generate", generate)
    preview = pb.run({"action": "build", "goal": "greet by name"}, registry)

    assert seen["target_os"] == "Windows"
    assert "Target OS: Windows" in preview
    assert "drafted" in preview


def test_builder_repairs_a_draft_for_the_wrong_operating_system(
    registry, isolated, monkeypatch,
):
    wrong_os_code = SAMPLE_CODE.replace('["Linux"]', '["Darwin"]')
    drafts = iter([wrong_os_code, SAMPLE_CODE])
    repairs = []

    def generate(goal, hint, key, research_results=None, repair_note=""):
        repairs.append(repair_note)
        return next(drafts)

    monkeypatch.setattr(pb, "_generate", generate)
    preview = pb.run({"action": "build", "goal": "greet by name"}, registry)

    assert "Target OS: Linux" in preview
    assert len(repairs) == 2
    assert "Unsupported on Linux" in repairs[1]
    assert "drafted" in preview


def test_search_plugin_uses_live_search_helper_when_dispatched(
    registry, isolated, monkeypatch,
):
    import actions.web_search as web_search

    plugin_code = '''from actions.web_search import search_results
PLUGIN = {
    "platforms": ["Linux"],
    "name": "lookup_tool",
    "description": "Looks up a topic using live web search.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"query": {"type": "STRING", "description": "Topic to search"}},
        "required": ["query"],
    },
}
def run(parameters, player=None, session_memory=None):
    query = (parameters or {}).get("query", "").strip()
    if not query:
        return "Please provide a search query."
    results = search_results(query, max_results=3)
    if not results:
        return "No live search results were returned."
    first = results[0]
    return f"{first['title']} — {first['url']}"
'''
    monkeypatch.setattr(
        web_search,
        "search_results",
        lambda query, max_results=6: [{
            "title": f"Fetched result for {query}",
            "snippet": "Live source snippet.",
            "url": "https://results.example/page",
        }],
    )
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: plugin_code)

    preview = pb.run({"action": "build", "goal": "look up a topic"}, registry)
    assert "drafted" in preview
    installed = pb.run(
        {"action": "build", "goal": "look up a topic", "name": "lookup_tool",
         "confirmed": True},
        registry,
    )

    assert "Installed" in installed
    result = registry.run("lookup_tool", {"query": "solar energy"})
    assert result == "Fetched result for solar energy — https://results.example/page"


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
    pb.run({"action": "build", "goal": "greet", "name": "hello_tool"}, registry)
    pb.run({"action": "build", "goal": "greet", "name": "hello_tool",
            "confirmed": True}, registry)
    out = pb.run({"action": "build", "goal": "greet again",
                  "name": "hello_tool", "confirmed": True}, registry)
    assert "already" in out


def test_fresh_confirmed_build_still_requires_preview_and_second_confirmation(
    registry, isolated, monkeypatch,
):
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: SAMPLE_CODE)

    preview = pb.run({"action": "build", "goal": "greet by name",
                      "name": "hello_tool", "confirmed": True}, registry)

    assert "drafted" in preview
    assert not registry.has("hello_tool")
    assert not (isolated / "plugins" / "hello_tool.py").exists()

    installed = pb.run({"action": "build", "goal": "greet by name",
                        "name": "hello_tool", "confirmed": True}, registry)

    assert "Installed" in installed
    assert registry.has("hello_tool")


def test_confirmation_for_a_different_goal_cannot_install_an_old_draft(
    registry, isolated, monkeypatch,
):
    monkeypatch.setattr(pb, "_generate", lambda goal, hint, key: SAMPLE_CODE)

    pb.run({"action": "build", "goal": "greet by name", "name": "hello_tool"}, registry)
    new_preview = pb.run({
        "action": "build", "goal": "calculate an average", "name": "hello_tool",
        "confirmed": True,
    }, registry)

    assert "drafted" in new_preview
    assert not registry.has("hello_tool")
    assert not (isolated / "plugins" / "hello_tool.py").exists()
