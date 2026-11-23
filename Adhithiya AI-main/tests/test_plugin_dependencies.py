"""Missing-software diagnostics are read-only and require a confirmed absence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import plugin_dependencies as deps
from core import plugin_loader


def _registry(run_fn):
    record = plugin_loader.PluginRecord(
        name="optional_tool", description="Uses an optional local dependency.",
        run=run_fn, valid=True,
    )
    return plugin_loader.PluginRegistry(
        {record.name: record}, lambda _message: None
    )


def test_registry_checks_for_missing_python_module_after_exception(monkeypatch):
    monkeypatch.setattr(deps, "_module_available", lambda _name: False)

    def run(parameters):
        raise ModuleNotFoundError(
            "No module named 'special_runtime'", name="special_runtime"
        )

    result = _registry(run).run("optional_tool", {})

    assert "required Python module(s) 'special_runtime'" in result
    assert "not available in ADHITHIYA's active environment" in result
    assert "python -m pip install special-runtime" in result
    assert "No module named 'special_runtime'" in result


def test_registry_checks_each_named_optional_package_in_failure_result(monkeypatch):
    monkeypatch.setattr(deps, "_module_available", lambda _name: False)

    def run(parameters):
        return "mac_media failed: Setting Windows volume needs the optional pycaw and comtypes packages."

    result = _registry(run).run("optional_tool", {})

    assert "'pycaw'" in result
    assert "'comtypes'" in result
    assert "pip install pycaw comtypes" in result


def test_missing_executable_is_checked_on_path_and_explained(monkeypatch):
    checked = []
    monkeypatch.setattr(
        deps.shutil, "which", lambda name: checked.append(name) or None
    )

    def run(parameters):
        return "Failed: Android Debug Bridge (adb) is not installed or not on PATH."

    result = _registry(run).run("optional_tool", {})

    assert "required executable 'adb' was not found on PATH" in result
    assert "uninstalled or installed outside PATH" in result
    assert "Android Debug Bridge (adb) is not installed" in result
    assert checked == ["adb"]


def test_present_dependency_is_not_blame_for_failure(monkeypatch):
    monkeypatch.setattr(deps, "_module_available", lambda _name: True)

    def run(parameters):
        return "optional_tool failed: No module named 'known_pkg'."

    result = _registry(run).run("optional_tool", {})

    assert result == "optional_tool failed: No module named 'known_pkg'."


def test_dependency_error_identifying_optional_executable_is_checked(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda _name: None)

    def run(parameters):
        return "Soduto/ADB failed: Device control needs scrcpy installed and on PATH."

    result = _registry(run).run("optional_tool", {})

    assert "required executable 'scrcpy' was not found on PATH" in result
    assert "scrcpy installed and on PATH" in result


def test_unhandled_subprocess_missing_executable_is_checked(monkeypatch):
    import subprocess

    monkeypatch.setattr(deps.shutil, "which", lambda _name: None)

    def run(parameters):
        subprocess.run(["/definitely/missing/adhithiya-test-command"], check=True)

    result = _registry(run).run("optional_tool", {})

    assert "required executable '/definitely/missing/adhithiya-test-command'" in result
    assert "not found on PATH" in result


def test_available_executable_is_not_reported_as_missing(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")

    def run(parameters):
        return "optional_tool failed: ffmpeg is not installed or not on PATH."

    result = _registry(run).run("optional_tool", {})

    assert result == "optional_tool failed: ffmpeg is not installed or not on PATH."


def test_generic_plugin_failure_and_missing_user_file_are_not_misdiagnosed(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda _name: None)
    monkeypatch.setattr(deps, "_module_available", lambda _name: False)

    assert deps.diagnose_missing_software(
        "optional_tool", "optional_tool failed: invalid configuration"
    ) == ""
    assert deps.diagnose_missing_software(
        "optional_tool", "Failed to open file: [Errno 2] No such file or directory: 'notes.txt'"
    ) == ""
