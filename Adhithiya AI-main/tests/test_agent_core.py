"""Tests for the agent core (task_runner) + web_fetch + image_generate. No network.

The agent loop talks to the model through ``core.llm.chat``, so we stub that
single function instead of faking a vendor client.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import task_runner
from core.project_agent import CommandPolicy


# ── fake core.llm.chat for the loop tests ────────────────────────────────────

def _tool_call(name, args, cid="call_1"):
    return {"id": cid, "name": name, "arguments": args}


def _resp_with_fc(name, args, cid="call_1"):
    return {"text": "", "tool_calls": [_tool_call(name, args, cid)]}


def _resp_with_text(text):
    return {"text": text, "tool_calls": []}


def _install_fake_chat(monkeypatch, script):
    """Replace core.llm.chat with a scripted responder (pops one reply per call)."""
    def _fake_chat(messages, tools=None, max_tokens=None, temp=None):
        assert script, "unexpected extra chat() call"
        return script.pop(0)

    monkeypatch.setattr("core.llm.chat", _fake_chat)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_loop_tool_then_final(monkeypatch):
    calls = []
    monkeypatch.setattr(task_runner, "_declarations", lambda: [])
    monkeypatch.setattr(task_runner, "_dispatch",
                        lambda name, args, player: calls.append(name) or ("search-result" if name == "web_search" else "done"))
    script = [_resp_with_fc("web_search", {"query": "x"}),
              _resp_with_fc("final_answer", {"text": "Finished."})]
    _install_fake_chat(monkeypatch, script)

    out = task_runner.run_task("test goal", api_key="k")
    assert out == "Finished."
    assert calls == ["web_search", "final_answer"]


def test_loop_text_only(monkeypatch):
    monkeypatch.setattr(task_runner, "_declarations", lambda: [])
    _install_fake_chat(monkeypatch, [_resp_with_text("All done here.")])
    assert task_runner.run_task("g", api_key="k") == "All done here."


def test_loop_max_steps(monkeypatch):
    monkeypatch.setattr(task_runner, "_declarations", lambda: [])
    monkeypatch.setattr(task_runner, "_dispatch", lambda n, a, p: "r")
    script = [_resp_with_fc("web_search", {})] * 5
    _install_fake_chat(monkeypatch, script)
    out = task_runner.run_task("g", api_key="k", max_steps=2)
    assert "Ran 2 steps" in out


def test_run_task_requires_key(monkeypatch):
    monkeypatch.setattr("core.llm.get_api_key", lambda: "")
    out = task_runner.run_task("g")
    assert "API key" in out


def test_command_policy_safety():
    ws = Path("/tmp/ws")
    policy = CommandPolicy(allowed=CommandPolicy.DEFAULT_ALLOWED)
    ok = policy.validate("pytest -q", ws, ws)
    assert ok.allowed and not ok.requires_approval
    assert policy.validate("git status", ws, ws).allowed
    assert not policy.validate("rm -rf /", ws, ws).allowed
    assert not policy.validate("curl http://x", ws, ws).allowed
    assert not policy.validate("python -c 'print(1)'", ws, ws).allowed
    assert not policy.validate("ls; rm x", ws, ws).allowed
    assert not policy.validate("sudo ls", ws, ws).allowed


def test_workspace_write_list_read(tmp_path, monkeypatch):
    monkeypatch.setattr(task_runner, "get_data_dir", lambda: tmp_path)
    r = task_runner._write_file("notes.md", "hello world")
    assert "notes.md" in r
    listing = task_runner._list_dir("workspace")
    assert "notes.md" in listing
    assert "hello world" in task_runner._read_file("workspace", "notes.md")


def test_web_fetch_extracts_text():
    from actions.web_fetch import _TextExtractor
    p = _TextExtractor()
    p.feed("<html><head><title>x</title></head><body><p>Hello</p><script>bad()</script><p>World</p></body></html>")
    assert "Hello" in p.text() and "World" in p.text() and "bad()" not in p.text()


def test_web_fetch_bad_url(monkeypatch):
    from actions import web_fetch
    assert "http" in web_fetch.web_fetch({"url": "not-a-url"})


def test_web_fetch_returns_raw_without_key(monkeypatch):
    from actions import web_fetch
    monkeypatch.setattr(web_fetch, "_fetch", lambda url: "<html><body>Plain page content here</body></html>")
    monkeypatch.setattr(web_fetch, "_api_key", lambda: "")
    out = web_fetch.web_fetch({"url": "https://example.com"})
    assert "Plain page content" in out


def test_image_generate_guards(monkeypatch):
    from actions import image_generate
    assert image_generate.image_generate({"prompt": ""}) == "Tell me what to draw (prompt)."
    monkeypatch.setattr(image_generate, "_api_key", lambda: "")
    assert "API key" in image_generate.image_generate({"prompt": "a cat"})
