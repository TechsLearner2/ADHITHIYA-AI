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


# ── web_search: every mode must use fetched results, never model memory ────────

def _fake_ddg_results(query, max_results=6):
    return [{
        "title": f"Fetched: {query}",
        "snippet": "This text came from the live-search backend.",
        "url": "https://x.example/article",
    }]


def test_default_search_returns_fetched_result(monkeypatch):
    monkeypatch.setattr(web_search, "_ddg_search", _fake_ddg_results)

    out = web_search._search("test query")

    assert "Live web search results" in out
    assert "Fetched: test query" in out
    assert "https://x.example/article" in out


def test_empty_search_is_not_replaced_with_an_unsourced_answer(monkeypatch):
    monkeypatch.setattr(web_search, "_ddg_search", lambda *_a, **_k: [])

    out = web_search._search("test query")

    assert out == "Live web search returned no source-linked results for: test query"


def test_search_results_uses_ddgs_and_sanitizes_source_urls(monkeypatch):
    calls = {}

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results):
            calls.update(query=query, max_results=max_results)
            return [
                {"title": "Real result", "body": "Fetched snippet.",
                 "href": "https://Example.com/article?ref=search#part"},
                {"title": "Unsafe URL", "body": "Do not keep this.",
                 "href": "javascript:alert(1)"},
            ]

    monkeypatch.setattr(web_search, "_get_ddgs", lambda: FakeDDGS)

    results = web_search.search_results("actual query", max_results=50)

    assert calls == {"query": "actual query", "max_results": 10}
    assert results == [{
        "title": "Real result",
        "snippet": "Fetched snippet.",
        "url": "https://example.com/article?ref=search",
    }]


@pytest.mark.parametrize("mode_fn", [
    web_search._research,
    web_search._price,
])
def test_research_and_price_use_live_results(monkeypatch, mode_fn):
    seen = []

    def fake_search(query, max_results=6):
        seen.append((query, max_results))
        return _fake_ddg_results(query, max_results)

    monkeypatch.setattr(web_search, "_ddg_search", fake_search)

    out = mode_fn("test query")

    assert "Fetched:" in out
    assert seen


def test_news_does_not_fabricate_headlines_when_search_is_empty(monkeypatch):
    monkeypatch.setattr(web_search, "_ddg_news", lambda *a, **k: [])

    out = web_search._news("test query")

    assert "no source-linked articles" in out


def test_compare_searches_each_item_and_preserves_sources(monkeypatch):
    calls = []

    def fake_search(query, max_results=6):
        calls.append(query)
        return _fake_ddg_results(query, max_results)

    monkeypatch.setattr(web_search, "_ddg_search", fake_search)

    out = web_search._compare(["item a", "item b"], "speed")

    assert calls == ["item a speed", "item b speed"]
    assert out.count("https://x.example/article") == 2
    assert "live search comparison" in out.lower()


def test_search_backend_error_is_reported_not_replaced_by_model_answer(monkeypatch):
    def fail_search(*args, **kwargs):
        raise web_search.WebSearchUnavailable("network unavailable")

    monkeypatch.setattr(web_search, "_ddg_search", fail_search)

    out = web_search.web_search({"query": "test query"})

    assert out == "Live web search failed: network unavailable"


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


# ── local mode: pre-warm the Ollama model so first questions don't stall ─────

def test_prewarm_ignored_outside_local_mode(monkeypatch):
    from core import llm
    monkeypatch.setattr(llm, "provider", lambda: "groq")
    assert llm.prewarm_local() is False


def test_prewarm_payload_requests_long_keepalive(monkeypatch):
    from core import llm
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "chat_model", lambda: "qwen3:8b")
    payload = llm._prewarm_payload()
    assert payload["model"] == "qwen3:8b"
    assert payload["prompt"] == ""                     # load only, no generation
    assert payload["keep_alive"] == llm._LOCAL_KEEP_ALIVE
    assert payload["keep_alive"].endswith(("m", "h"))  # a real duration, not ""


def test_prewarm_posts_keepalive_request(monkeypatch):
    """The background thread must actually POST to /api/generate (best-effort,
    never raising into the caller)."""
    import threading
    import urllib.request

    from core import llm

    seen = {}
    done = threading.Event()

    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        done.set()
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "chat_model", lambda: "qwen3:8b")

    assert llm.prewarm_local() is True
    assert done.wait(2), "pre-warm thread never issued its request"
    assert seen["url"].endswith("/api/generate")
    assert seen["body"]["model"] == "qwen3:8b"
    assert seen["body"]["keep_alive"] == llm._LOCAL_KEEP_ALIVE
    assert seen["timeout"] >= 120   # room for a slow CPU cold load


def test_prewarm_survives_network_failure(monkeypatch):
    """A dead Ollama must not leak an exception from the warm-up thread."""
    import urllib.request

    from core import llm

    def dead_urlopen(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", dead_urlopen)
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "chat_model", lambda: "qwen3:8b")
    assert llm.prewarm_local() is True   # started; failure logged, not raised


# ── local mode: qwen3 think-blocks must never be spoken ──────────────────────

def test_strip_think_removes_inline_monologue():
    from core import llm
    # exact shape observed from qwen3:8b via Ollama's OpenAI endpoint
    raw = ('<think>\nOkay, the user said "Say OK". Long reasoning here.\n'
           '</think>\n\nSure! What\'s on your mind?')
    assert llm._strip_think(raw) == "Sure! What's on your mind?"
    assert llm._strip_think("no blocks here") == "no blocks here"


def _fake_openai_client(reply_text: str, seen: dict):
    from types import SimpleNamespace

    class _Completions:
        def create(self, **kwargs):
            seen["kwargs"] = kwargs
            msg = SimpleNamespace(content=reply_text, tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class _Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=_Completions())

    return _Client()


def test_chat_strips_think_block_and_appends_no_think(monkeypatch):
    from core import llm

    seen: dict = {}
    monkeypatch.setattr(llm, "_client", lambda: _fake_openai_client(
        "<think>secret monologue</think>\n\nHello!", seen))
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "_chat_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(llm, "_cfg", lambda: {"local_no_think": True})

    original = [{"role": "system", "content": "You are ADHITHIYA."},
                {"role": "user", "content": "hi"}]
    out = llm.chat(original)

    assert out["text"] == "Hello!"                    # monologue never spoken
    sent = seen["kwargs"]["messages"]
    assert sent[0]["content"].endswith("/no_think")   # switch applied on wire
    assert original[0]["content"] == "You are ADHITHIYA."  # caller unmutated


def test_chat_leaves_messages_alone_without_the_toggle(monkeypatch):
    from core import llm

    seen: dict = {}
    monkeypatch.setattr(llm, "_client", lambda: _fake_openai_client("Hi", seen))
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "_chat_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(llm, "_cfg", lambda: {})

    msgs = [{"role": "user", "content": "hi"}]
    assert llm.chat(msgs)["text"] == "Hi"
    assert seen["kwargs"]["messages"] == msgs         # untouched without flag


def test_no_think_switch_skips_non_qwen_models(monkeypatch):
    """/no_think is a Qwen3 soft switch — phi3 (and friends) neither emit
    <think> blocks nor understand the switch, so their prompts stay clean."""
    from core import llm

    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "_cfg", lambda: {"local_no_think": True})

    phi = [{"role": "user", "content": "hi"}]
    monkeypatch.setattr(llm, "chat_model", lambda: "phi3:mini")
    assert llm._local_no_think_messages(phi) is phi   # untouched

    qwen = [{"role": "system", "content": "You are ADHITHIYA."}]
    monkeypatch.setattr(llm, "chat_model", lambda: "qwen3:8b")
    out = llm._local_no_think_messages(qwen)
    assert out[0]["content"].endswith("/no_think")     # qwen still gets it


# ── system monitor: never blame the user for our own brain thinking ──────────

def test_chat_marks_local_busy_and_clears_it_after(monkeypatch):
    """While a local chat request is in flight local_busy() must be True, and
    it must return to False even when the request raises (finally)."""
    from types import SimpleNamespace

    from core import llm

    monkeypatch.setattr(llm, "_LOCAL_BUSY", 0)
    seen: dict = {}

    class _Completions:
        def create(self, **kwargs):
            seen["busy_during_request"] = llm.local_busy()
            raise ConnectionError("[Errno 61] Connection refused")

    monkeypatch.setattr(llm, "_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(
                            completions=_Completions())))
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "_chat_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(llm, "_cfg", lambda: {})

    with pytest.raises(RuntimeError):
        llm.chat([{"role": "user", "content": "hi"}])

    assert seen["busy_during_request"] is True
    assert llm.local_busy() is False                 # finally restored it


def test_prewarm_marks_busy_while_loading(monkeypatch):
    import threading
    import time
    import urllib.request

    from core import llm

    monkeypatch.setattr(llm, "_LOCAL_BUSY", 0)
    seen: dict = {}
    done = threading.Event()

    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen["busy_during_warm"] = llm.local_busy()
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "chat_model", lambda: "qwen3:8b")
    monkeypatch.setattr(llm, "_cfg", lambda: {})

    assert llm.prewarm_local() is True
    for _ in range(100):             # wait for the daemon thread to finish
        if llm.local_busy() is False and "busy_during_warm" in seen:
            break
        time.sleep(0.02)

    assert seen.get("busy_during_warm") is True
    assert llm.local_busy() is False


def _silent_psutil(monkeypatch, cpu, ram, temp, gpu):
    from types import SimpleNamespace

    from actions import system_monitor as sm

    monkeypatch.setattr(sm.psutil, "cpu_percent", lambda interval=None: cpu)
    monkeypatch.setattr(sm.psutil, "virtual_memory",
                        lambda: SimpleNamespace(percent=ram))
    monkeypatch.setattr(sm, "_get_cpu_temp", lambda: temp)
    monkeypatch.setattr(sm, "_get_gpu_usage", lambda: gpu)
    return sm


def test_monitor_silent_while_local_brain_busy(monkeypatch):
    """A pinned CPU during local inference (or pre-warm) is the brain working,
    not a runaway app — no alert, and the streak resets so no deferred alert
    fires the instant it finishes unless CPU stays high for real."""
    sm = _silent_psutil(monkeypatch, cpu=99.0, ram=50.0, temp=0.0, gpu=-1.0)
    monkeypatch.setattr("core.llm.local_busy", lambda: True)

    mon = sm.SystemMonitor()
    for _ in range(sm._CPU_STREAK + 2):
        assert mon.check() is None


def test_monitor_alerts_natural_text_when_idle(monkeypatch):
    import time

    sm = _silent_psutil(monkeypatch, cpu=95.0, ram=50.0, temp=0.0, gpu=-1.0)
    monkeypatch.setattr("core.llm.local_busy", lambda: False)

    mon = sm.SystemMonitor()
    # cooldown treats "never alerted" as t=0, so on a freshly booted machine
    # (<5 min uptime) alerts are intentionally still in grace — age the clock
    mon._last_alert["cpu"] = time.monotonic() - (sm._COOLDOWN + 1)
    alert = None
    for _ in range(sm._CPU_STREAK + 2):
        alert = mon.check() or alert   # keep the first alert; later checks cool down
    assert alert
    assert "CPU" in alert
    # speak() pipes this verbatim into TTS — internal instructions and
    # markup must never reach the user's ears
    assert "Warn the user" not in alert
    assert "[SYSTEM_ALERT]" not in alert


def test_monitor_temp_alert_also_paused_while_busy(monkeypatch):
    sm = _silent_psutil(monkeypatch, cpu=50.0, ram=50.0, temp=95.0, gpu=-1.0)
    monkeypatch.setattr("core.llm.local_busy", lambda: True)
    mon = sm.SystemMonitor()
    for _ in range(sm._CPU_STREAK + 2):
        assert mon.check() is None


# ── speech: a new message must never truncate the one still playing ─────────

def test_new_speech_waits_for_inflight_playback():
    """Two speak() calls colliding (error apology + system alert) used to
    drain the first message's still-playing audio mid-word. _speak_text now
    awaits _wait_playback_idle() first: wait while speaking/queued, bounded
    by a timeout so a dead output device can't wedge the queue."""
    import asyncio
    import time as _t

    try:
        import main
    except Exception as e:  # headless box without DISPLAY / audio stack
        pytest.skip(f"main not importable here: {e}")

    class _Fake:
        def __init__(self):
            self._is_speaking = True
            self.audio_in_queue = asyncio.Queue()

    fake = _Fake()

    async def drive():
        async def unstick():
            await asyncio.sleep(0.2)
            fake._is_speaking = False
        asyncio.create_task(unstick())
        t0 = _t.monotonic()
        await main.AdhithiyaAssistant._wait_playback_idle(fake, timeout=5)
        return _t.monotonic() - t0

    waited = asyncio.run(drive())
    assert 0.15 < waited < 2, waited      # it genuinely waited, then proceeded

    fake2 = _Fake()                       # playback stuck forever…

    async def stuck():
        t0 = _t.monotonic()
        await main.AdhithiyaAssistant._wait_playback_idle(fake2, timeout=0.3)
        return _t.monotonic() - t0

    waited2 = asyncio.run(stuck())
    assert 0.25 < waited2 < 2, waited2    # …bounded by the timeout, not a hang


def test_long_tts_stream_backpressures_instead_of_truncating(monkeypatch):
    """A bounded playback queue must not silently cut off long TTS replies."""
    import asyncio

    try:
        import main
        from core import llm
    except Exception as e:  # headless box without the audio/UI stack
        pytest.skip(f"main not importable here: {e}")

    pcm = b"x" * (2400 * 60 + 123)  # longer than the normal queue can hold
    monkeypatch.setattr(llm, "tts_wav", lambda _text: b"fake-wav")

    async def no_wait():
        return None

    fake = SimpleNamespace(
        _asst_name="ADHITHIYA",
        ui=SimpleNamespace(write_log=lambda _message: None),
        _session_log=[],
        _dashboard=None,
        _wav_to_pcm=lambda _wav, _rate: pcm,
        _wait_playback_idle=no_wait,
        _interrupted=False,
        audio_in_queue=asyncio.Queue(maxsize=2),
        _turn_done_event=asyncio.Event(),
    )

    async def drive():
        async def consume():
            played = bytearray()
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        fake.audio_in_queue.get(), timeout=0.1)
                    played.extend(chunk)
                except asyncio.TimeoutError:
                    if fake._turn_done_event.is_set() and fake.audio_in_queue.empty():
                        return bytes(played)

        consumer = asyncio.create_task(consume())
        await main.AdhithiyaAssistant._speak_text(fake, "a long reply")
        return await asyncio.wait_for(consumer, timeout=3)

    assert asyncio.run(drive()) == pcm


# ── dashboard thread → QR overlay must hop to the GUI thread ─────────────────

def test_local_failure_message_carries_the_cause(monkeypatch):
    """'Ollama isn't answering' must include the underlying error so a dead
    server (ECONNREFUSED) is distinguishable from a timeout when debugging
    from the app's log."""
    from types import SimpleNamespace

    from core import llm

    class _Completions:
        def create(self, **kwargs):
            raise ConnectionError("[Errno 61] Connection refused")

    monkeypatch.setattr(llm, "_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(
                            completions=_Completions())))
    monkeypatch.setattr(llm, "provider", lambda: "local")
    monkeypatch.setattr(llm, "_chat_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(llm, "_cfg", lambda: {})

    with pytest.raises(RuntimeError) as excinfo:
        llm.chat([{"role": "user", "content": "hi"}])
    msg = str(excinfo.value)
    assert "Ollama isn't answering" in msg
    assert "ConnectionError" in msg          # the cause is now visible
    assert "refused" in msg


def test_mark_connected_from_dashboard_thread():
    """The dashboard reports phone pairing from its uvicorn thread. Calling
    mark_connected() there used to stop a QTimer from the wrong thread
    ('QObject::killTimer: Timers cannot be stopped from another thread').
    The public method must only emit; all UI work lands on the GUI thread."""
    import os
    import threading
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets",
                        reason="UI toolkit / native Qt libs not installed")
    from PyQt6.QtWidgets import QApplication

    from ui import RemoteKeyOverlay

    app = QApplication.instance() or QApplication([])
    ov = RemoteKeyOverlay(url="http://192.168.1.100:8000", key="ABC234",
                          manual_url="192.168.1.100:8000")
    assert ov._ctimer.isActive()

    emitted = threading.Event()

    def dashboard_thread():
        ov.mark_connected()          # must be safe: no direct QObject calls
        emitted.set()

    threading.Thread(target=dashboard_thread, daemon=True).start()
    assert emitted.wait(2)

    for _ in range(50):              # pump the queued connection
        app.processEvents()
        if ov._key_lbl.text() == "CONNECTED":
            break
        time.sleep(0.02)

    assert ov._key_lbl.text() == "CONNECTED"
    assert not ov._ctimer.isActive()
