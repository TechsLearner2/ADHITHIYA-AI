"""Regressions for deterministic opening, plugin routing, and evidence-gated learning."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

from actions import browser_control as browser
from actions import file_controller as files
from actions import open_app as opening
from core import plugin_loader
from core.deduplication import RecentRequestGuard, ToolCallDeduplicator
from core.tool_results import is_learnable_failure, is_tool_failure
from memory import self_learning as learning


# ── App/file opening ────────────────────────────────────────────────────────


def test_app_aliases_are_exact_not_substring_matches(monkeypatch):
    monkeypatch.setattr(opening, "_SYSTEM", "Linux")

    assert opening._normalize("  Google Chrome  ") == "google-chrome"
    assert opening._normalize("chromebook") == "chromebook"
    assert opening._normalize("Netflix") == "Netflix"


def test_known_web_service_redirects_to_browser_control(monkeypatch):
    seen = {}

    def fake_browser_control(parameters, player=None):
        seen["parameters"] = parameters
        seen["player"] = player
        return "The OS accepted the request to open Netflix in your default browser."

    monkeypatch.setattr(browser, "browser_control", fake_browser_control)
    result = opening.open_app({"app_name": "Netflix", "browser": "edge"})

    assert seen["parameters"]["url"] == "https://www.netflix.com/"
    assert seen["parameters"]["browser"] == "edge"
    assert "accepted the request" in result


def test_open_app_does_not_claim_success_when_launcher_rejects(monkeypatch):
    monkeypatch.setattr(opening, "_SYSTEM", "Linux")
    monkeypatch.setattr(opening, "_OS_LAUNCHERS", {"Linux": lambda _name: False})

    result = opening.open_app({"app_name": "My Uninstalled App"})

    assert "Could not confirm" in result
    assert "accepted the launch request" not in result


def test_open_app_reports_os_acceptance_without_claiming_visible_window(monkeypatch):
    monkeypatch.setattr(opening, "_SYSTEM", "Linux")
    monkeypatch.setattr(opening, "_OS_LAUNCHERS", {"Linux": lambda _name: True})

    result = opening.open_app({"app_name": "Chrome"})

    assert "operating system accepted" in result
    assert "not independently verified" in result
    assert not result.startswith("Opened ")


def test_linux_app_launcher_never_uses_xdg_open_for_an_app_name(monkeypatch):
    monkeypatch.setattr(opening.shutil, "which", lambda _name: None)
    monkeypatch.setattr(opening.subprocess, "run", lambda *a, **k: pytest.fail("unexpected launcher"))

    assert opening._launch_linux("not-an-installed-app") is False


def test_windows_start_menu_resolution_is_exact(monkeypatch, tmp_path):
    root = tmp_path / "Programs"
    root.mkdir()
    (root / "Google Chrome.lnk").touch()
    opened = []
    monkeypatch.setattr(opening.shutil, "which", lambda _name: None)
    monkeypatch.setattr(opening, "_windows_shortcut_roots", lambda: [root])
    monkeypatch.setattr(opening.os, "startfile", lambda path: opened.append(path), raising=False)

    assert opening._launch_windows("Google Chrome") is True
    assert not opening._launch_windows("Chrome Canary")
    assert len(opened) == 1
    assert opened[0].endswith("Google Chrome.lnk")


def test_requested_browser_does_not_silently_fall_back(monkeypatch):
    monkeypatch.setattr(browser, "_OS", "Linux")
    monkeypatch.setattr(browser, "_resolve_browser", lambda _name: None)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *a, **k: pytest.fail("wrong browser fallback"))

    result = browser._open_native("https://example.com", "safari")

    assert "requested browser 'safari'" in result
    assert "no browser was launched" in result


def test_file_open_checks_path_and_os_return_code(monkeypatch, tmp_path):
    item = tmp_path / "notes.txt"
    item.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(files, "_OS", "Linux")
    monkeypatch.setattr(files, "_SAFE_ROOTS", [tmp_path])
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(files.subprocess, "run", fake_run)
    result = files.open_item(str(item))

    assert seen["command"] == ["xdg-open", str(item)]
    assert "operating system accepted" in result
    assert "not independently verified" in result


def test_file_open_does_not_report_os_failure_as_success(monkeypatch, tmp_path):
    item = tmp_path / "notes.txt"
    item.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(files, "_OS", "Linux")
    monkeypatch.setattr(files, "_SAFE_ROOTS", [tmp_path])
    monkeypatch.setattr(
        files.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stderr=b"no handler"),
    )

    result = files.open_item(str(item))

    assert "Could not open" in result
    assert "OS accepted" not in result


def test_file_open_keeps_home_safety_boundary(monkeypatch, tmp_path):
    safe_root = tmp_path / "home"
    outside = tmp_path / "outside.txt"
    safe_root.mkdir()
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(files, "_SAFE_ROOTS", [safe_root])

    result = files.open_item(str(outside))

    assert result.startswith("Access denied:")


# ── Duplicate requests/actions ────────────────────────────────────────────────


def test_recent_request_guard_suppresses_only_short_exact_repeats():
    guard = RecentRequestGuard(window_seconds=2.5)

    assert not guard.is_duplicate("  Open Chrome  ", now=10.0)
    assert guard.is_duplicate("open   chrome", now=11.0)
    assert not guard.is_duplicate("Open Chrome", now=12.6)


def test_tool_call_guard_canonicalizes_args_and_caches_result():
    guard = ToolCallDeduplicator()
    assert guard.previous_result("open_app", {"app_name": "Chrome"}) is None

    guard.remember("open_app", {"app_name": "Chrome", "browser": None}, "accepted")

    assert guard.previous_result(
        "open_app", {"browser": None, "app_name": "Chrome"}
    ) == "accepted"
    assert guard.previous_result("open_app", {"app_name": "Firefox"}) is None
    assert guard.previous_result("file_controller", {"app_name": "Chrome", "browser": None}) is None


# ── Plugin invocation and platform filtering ─────────────────────────────────


def test_legacy_plugin_schema_fields_are_passed_by_name():
    def legacy_run(action, volume_level=None, setting_pane=None):
        return f"{action}:{volume_level}:{setting_pane}"

    record = plugin_loader.PluginRecord(
        name="legacy", description="legacy test", run=legacy_run, valid=True
    )
    registry = plugin_loader.PluginRegistry({"legacy": record}, lambda _message: None)

    assert registry.run("legacy", {
        "action": "set_volume", "volume_level": 35,
    }) == "set_volume:35:None"


def test_dictionary_plugin_contract_still_receives_context():
    player = object()
    session = object()
    seen = {}

    def run(parameters, player=None, session_memory=None):
        seen.update(parameters=parameters, player=player, session=session_memory)
        return "ok"

    assert plugin_loader._call_run(run, {"action": "list"}, player, session) == "ok"
    assert seen == {"parameters": {"action": "list"}, "player": player, "session": session}


def test_platform_specific_plugin_is_not_advertised_elsewhere(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    extra = tmp_path / "extra"
    bundled.mkdir()
    extra.mkdir()
    (extra / "mac_only.py").write_text(
        "PLUGIN = {\n"
        " 'name': 'mac_only', 'description': 'Mac only test',\n"
        " 'platforms': ['Darwin'],\n"
        " 'parameters': {'type': 'OBJECT', 'properties': {}},\n"
        "}\n"
        "def run(parameters): return 'ok'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_loader.platform, "system", lambda: "Linux")

    registry = plugin_loader.discover_plugins(
        plugins_dir=bundled,
        core_tool_names=set(),
        logger=lambda _message: None,
        extra_dirs=[(extra, "test_platform_plugins")],
    )

    assert not registry.has("mac_only")
    assert registry.get_tool_declarations() == []
    listed = registry.list_for_ui()
    assert listed[0]["valid"] is False
    assert "supports: Darwin" in listed[0]["error"]


def test_registry_rechecks_os_before_advertising_or_running(monkeypatch):
    monkeypatch.setattr(plugin_loader.platform, "system", lambda: "Windows")

    def run(parameters):
        return "should not run"

    record = plugin_loader.PluginRecord(
        name="mac_only", description="Mac-only", run=run, valid=True,
        platforms=("Darwin",),
    )
    registry = plugin_loader.PluginRegistry({"mac_only": record}, lambda _message: None)

    assert registry.get_tool_declarations() == []
    assert "supports Darwin, not the current OS (Windows)" in registry.run("mac_only", {})
    assert "targets Darwin, not the current OS (Windows)" in registry.register(record)


def test_plugin_exception_string_is_counted_as_failure_not_success():
    failure = "Sir, the 'broken_tool' plugin failed: missing executable"

    assert is_tool_failure(failure)
    assert is_learnable_failure(failure)
    assert not is_learnable_failure("Please provide the missing title.")
    assert not is_tool_failure("The operating system accepted the launch request.")


# ── Evidence-gated self-learning ────────────────────────────────────────────


def test_learning_skips_missing_or_irrelevant_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(learning, "LEARNED_PATH", tmp_path / "learned.json")
    irrelevant = [{
        "title": "How to prepare garden soil",
        "body": "Compost improves drainage for tomatoes.",
        "href": "https://gardening.example/article",
    }]
    monkeypatch.setattr(learning, "_ddg_search", lambda _query: irrelevant)
    monkeypatch.setattr(
        learning, "_distill",
        lambda *args: pytest.fail("the model must not be asked without relevant evidence"),
    )

    result = learning.learn_from_failure(
        "ffmpeg", {}, "ffmpeg command not found", api_key="test-key"
    )

    assert result == ""
    assert not (tmp_path / "learned.json").exists()


def test_learning_rejects_a_fix_with_unsupported_command_terms(monkeypatch, tmp_path):
    monkeypatch.setattr(learning, "LEARNED_PATH", tmp_path / "learned.json")
    search_result = [{
        "title": "FFmpeg install guide",
        "body": "On Linux, install ffmpeg using apt.",
        "href": "https://docs.example/ffmpeg?tracking=secret",
    }]
    monkeypatch.setattr(learning, "_ddg_search", lambda _query: search_result)
    monkeypatch.setattr(
        learning, "_distill",
        lambda *args: "Run `sudo apt install made-up-codec` to fix FFmpeg.",
    )

    result = learning.learn_from_failure(
        "ffmpeg", {}, "ffmpeg command not found", api_key="test-key"
    )

    assert result == ""
    assert not (tmp_path / "learned.json").exists()


def test_learning_saves_only_grounded_guidance_with_source_domain(monkeypatch, tmp_path):
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learning, "LEARNED_PATH", path)
    search_result = [{
        "title": "FFmpeg install guide",
        "body": "Install ffmpeg using Homebrew. Command: brew install ffmpeg.",
        "href": "https://docs.example/ffmpeg?tracking=secret",
    }]
    monkeypatch.setattr(learning, "_ddg_search", lambda _query: search_result)
    guidance = "Run `brew install ffmpeg` with Homebrew to install FFmpeg."
    monkeypatch.setattr(learning, "_distill", lambda *args: guidance)

    result = learning.learn_from_failure(
        "ffmpeg", {}, "ffmpeg command not found", api_key="test-key"
    )

    assert result == guidance
    saved = path.read_text(encoding="utf-8")
    assert "docs.example" in saved
    assert "tracking=secret" not in saved
    assert "tracking=secret" not in learning.format_learned_for_prompt()


def test_legacy_learned_guidance_without_evidence_is_not_in_prompt(monkeypatch, tmp_path):
    path = tmp_path / "learned.json"
    path.write_text(
        '{"open_app":{"issues":[{"guidance":"Install a guessed package."}]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(learning, "LEARNED_PATH", path)

    assert learning.format_learned_for_prompt() == ""


def test_learning_uses_the_shared_live_search_backend(monkeypatch):
    from actions import web_search
    seen = {}
    expected = [{
        "title": "FFmpeg install guide",
        "snippet": "Use Homebrew to install ffmpeg.",
        "url": "https://docs.example/ffmpeg",
    }]

    def fake_search(query, max_results=6):
        seen.update(query=query, max_results=max_results)
        return expected

    monkeypatch.setattr(web_search, "search_results", fake_search)

    assert learning._ddg_search("ffmpeg error", max_results=4) == expected
    assert seen == {"query": "ffmpeg error", "max_results": 4}


def test_search_evidence_without_api_key_is_not_reported_as_learned(
    monkeypatch, tmp_path,
):
    path = tmp_path / "learned.json"
    monkeypatch.setattr(learning, "LEARNED_PATH", path)
    results = [{
        "title": "FFmpeg install guide",
        "body": "Install ffmpeg using Homebrew. Command: brew install ffmpeg.",
        "href": "https://docs.example/ffmpeg",
    }]
    monkeypatch.setattr(learning, "_ddg_search", lambda _query: results)
    monkeypatch.setattr(
        learning, "_distill",
        lambda *args: pytest.fail("must not distill without an API key"),
    )

    result = learning.learn_from_failure(
        "ffmpeg", {}, "ffmpeg command not found", api_key=""
    )

    assert result == ""
    assert not path.exists()


def test_learning_does_not_report_success_when_persistence_fails(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(learning, "LEARNED_PATH", tmp_path / "learned.json")
    results = [{
        "title": "FFmpeg install guide",
        "body": "Install ffmpeg using Homebrew. Command: brew install ffmpeg.",
        "href": "https://docs.example/ffmpeg",
    }]
    monkeypatch.setattr(learning, "_ddg_search", lambda _query: results)
    monkeypatch.setattr(
        learning, "_distill",
        lambda *args: "Run `brew install ffmpeg` with Homebrew to install FFmpeg.",
    )
    monkeypatch.setattr(
        learning, "_save",
        lambda _data: (_ for _ in ()).throw(OSError("read-only storage")),
    )

    result = learning.learn_from_failure(
        "ffmpeg", {}, "ffmpeg command not found", api_key="test-key"
    )

    assert result == ""
