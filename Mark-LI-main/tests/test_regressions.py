"""Regressions for bugs found by static analysis (2026-09).

Two NameErrors had shipped because the names were only ever referenced inside
fallback / agent paths the test suite never walked:

* ``actions.web_search`` called an undefined ``_log_failure`` inside every
  except-branch — so exactly when the LLM failed, the *fallback* crashed too.
* ``actions.dev_agent`` referenced ``MODEL_PLANNER`` / ``MODEL_WRITER``
  constants that were never defined — any project-build task died instantly.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions import web_search
from actions import dev_agent


# ── web_search: the DDG fallback must survive an LLM failure ─────────────────

def _fake_ddg_results(query, max_results=6):
    return [{"title": f"t {query}", "snippet": "ddg-snippet", "url": "https://x.example"}]


@pytest.mark.parametrize("mode_fn", [
    web_search._search,
    lambda q: web_search._research(q),
    lambda q: web_search._price(q),
])
def test_llm_failure_falls_back_to_ddg(monkeypatch, mode_fn):
    """LLM raises → the except-branch must log (not crash) and return DDG text.

    Before the fix this raised NameError: _log_failure didn't exist, so the
    DuckDuckGo fallback never ran at all.
    """
    def _boom(query):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(web_search, "_llm_answer", _boom)
    monkeypatch.setattr(web_search, "_ddg_search", _fake_ddg_results)
    monkeypatch.setattr(web_search, "_format_ddg",
                        lambda q, results: f"FORMATTED({q}, {len(results)})")

    out = mode_fn("test query")
    assert out == "FORMATTED(test query, 1)"


def test_compare_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(web_search, "_llm_answer",
                        lambda q: (_ for _ in ()).throw(RuntimeError("LLM down")))
    monkeypatch.setattr(web_search, "_ddg_search", _fake_ddg_results)

    out = web_search._compare(["a", "b"], "speed")
    assert "ddg-snippet" in out


# ── dev_agent: planner/writer stages must be callable ────────────────────────

class _FakeModel:
    """Stands in for _get_model(): returns the canned LLM payload."""
    def __init__(self, payload: str):
        self._payload = payload

    def generate_content(self, contents):
        return SimpleNamespace(text=self._payload)


def test_plan_project_returns_parsed_plan(monkeypatch):
    plan = {
        "project_name": "tiny",
        "entry_point": "main.py",
        "files": [{"path": "main.py", "description": "entry", "imports": []}],
        "run_command": "python main.py",
        "dependencies": [],
    }
    monkeypatch.setattr(dev_agent, "_get_model",
                        lambda name="": _FakeModel(json.dumps(plan)))

    got = dev_agent._plan_project("a tiny cli tool", "python")
    assert got["project_name"] == "tiny"
    assert got["files"][0]["path"] == "main.py"


def test_write_file_uses_writer_model(monkeypatch, tmp_path):
    monkeypatch.setattr(dev_agent, "_get_model",
                        lambda name="": _FakeModel("print('hi')\n"))

    code = dev_agent._write_file(
        {"path": "main.py", "description": "entry", "imports": []},
        "a tiny tool", [{"path": "main.py"}], "python",
        tmp_path, {},
    )
    assert "print" in code
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('hi')"


# ── config: saves must be atomic and private (the file holds API keys) ───────

def test_api_key_file_is_private_and_atomic(monkeypatch, tmp_path):
    import os

    from memory import config_manager as cm

    cfg = tmp_path / "api_keys.json"
    monkeypatch.setattr(cm, "CONFIG_FILE", cfg)
    monkeypatch.setattr(cm, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cm, "get_base_dir", lambda: tmp_path / "no-legacy")

    cm.save_api_keys("gsk_TESTKEY", "groq")

    assert cfg.exists()
    assert cfg.read_text(encoding="utf-8").count("gsk_TESTKEY") == 1
    # 0600 — group/other must not read the key file.
    assert (cfg.stat().st_mode & 0o777) == 0o600
    # atomic save leaves no temp file behind
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
