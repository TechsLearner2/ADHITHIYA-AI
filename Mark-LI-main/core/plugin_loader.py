"""
Plugin discovery, validation, collision detection, and dispatch.

Discovery runs once (JarvisLive.__init__ calls discover_plugins()); the resulting
PluginRegistry is cached for the process lifetime. Enable/disable state is re-read
from config on every call to get_tool_declarations() / run() / list_for_ui(), so
toggling a plugin does not require restarting the app or re-importing anything.

Two plugin homes are scanned:

* the bundled ``plugins/`` directory (read-only inside a frozen .app), and
* the user plugins directory ``~/.adhithiya/plugins/`` where ADHITHIYA's
  self-authoring (the plugin_builder tool) installs new abilities the user has
  approved. User plugins load under the ``adhithiya_plugins`` module prefix so
  they never shadow bundled plugins or each other's relative imports.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from memory.config_manager import get_plugin_enabled

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}}

# Where ADHITHIYA's self-authored plugins live — always user-writable and
# survives app updates / frozen .app builds.
USER_PLUGINS_DIR = Path.home() / ".adhithiya" / "plugins"
USER_PLUGINS_PREFIX = "adhithiya_plugins"


@dataclass
class PluginRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    run: Optional[Callable] = None
    file: str = ""
    valid: bool = False
    error: str = ""


class PluginRegistry:
    def __init__(self, plugins: dict[str, PluginRecord], logger: Callable[[str], None],
                 core_tool_names: Optional[set[str]] = None):
        self._plugins = plugins          # name -> PluginRecord, VALID entries only
        self._all_records: list[PluginRecord] = []   # valid + invalid, for UI listing
        self._logger = logger
        self._core_tool_names = set(core_tool_names or ())

    # -- called by main.py at LiveConnectConfig build time --
    def get_tool_declarations(self) -> list[dict]:
        decls = []
        for name, rec in self._plugins.items():
            if get_plugin_enabled(name):
                decls.append({
                    "name": rec.name,
                    "description": rec.description,
                    "parameters": rec.parameters,
                })
        return decls

    def has(self, name: str) -> bool:
        return name in self._plugins

    # -- called by main.py from _execute_tool's else branch --
    def run(self, name: str, parameters: dict, player=None, session_memory=None) -> str:
        rec = self._plugins.get(name)
        if rec is None or not rec.valid:
            return f"Plugin '{name}' is not available."
        if not get_plugin_enabled(name):
            return f"The '{name}' plugin is currently disabled."
        try:
            return _call_run(rec.run, parameters, player, session_memory) or "Done."
        except Exception as e:
            self._logger(f"Plugin '{name}' crashed during run(): {e}")
            traceback.print_exc()
            return f"Sir, the '{name}' plugin failed: {e}"

    # -- called by ui.py's Plugin Manager overlay --
    def list_for_ui(self) -> list[dict]:
        out = []
        for rec in self._all_records:
            out.append({
                "name": rec.name,
                "description": rec.description,
                "file": rec.file,
                "valid": rec.valid,
                "error": rec.error,
                "enabled": get_plugin_enabled(rec.name) if rec.valid else False,
            })
        return out

    # -- called by the plugin_builder tool (self-authoring) --
    def register(self, rec: PluginRecord) -> str:
        """Install a freshly built, already-imported + validated plugin at runtime.

        Returns '' on success, or a human-readable error string.
        """
        if not rec.valid:
            return rec.error or "The new plugin failed validation."
        if rec.name in self._core_tool_names:
            return f"Name '{rec.name}' collides with a built-in tool — choose another name."
        if rec.name in self._plugins:
            return f"A plugin named '{rec.name}' is already loaded."
        self._plugins[rec.name] = rec
        self._all_records.append(rec)
        self._logger(f"Plugin built and loaded: {rec.name} ({rec.file})")
        return ""

    def unregister(self, name: str) -> bool:
        """Remove a runtime-registered plugin; True if it was present."""
        rec = self._plugins.pop(name, None)
        if rec is not None:
            self._all_records = [r for r in self._all_records if r is not rec]
            self._logger(f"Plugin removed: {name}")
            return True
        return False


def _call_run(run_fn, parameters, player, session_memory):
    """Invoke run() passing only the kwargs it actually declares (or all of them
    if it has **kwargs), so a minimal `def run(parameters):` plugin still works."""
    sig = inspect.signature(run_fn)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs = {}
    if has_var_kw or "player" in sig.parameters:
        kwargs["player"] = player
    if has_var_kw or "session_memory" in sig.parameters:
        kwargs["session_memory"] = session_memory
    return run_fn(parameters, **kwargs)


def _validate(module, filename: str) -> PluginRecord:
    """Returns a PluginRecord; .valid=False + .error set on any problem. Never raises."""
    plugin_meta = getattr(module, "PLUGIN", None)
    if not isinstance(plugin_meta, dict):
        return PluginRecord(name=Path(filename).stem, file=filename,
                             error="Missing PLUGIN dict constant.")

    name = plugin_meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return PluginRecord(name=str(name or Path(filename).stem), file=filename,
                             error="PLUGIN['name'] missing or not a valid identifier "
                                   "(letters/digits/underscore, must start with letter/underscore).")

    description = plugin_meta.get("description")
    if not isinstance(description, str) or not description.strip():
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['description'] missing or empty.")

    parameters = plugin_meta.get("parameters", _DEFAULT_PARAMS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        return PluginRecord(name=name, file=filename,
                             error="PLUGIN['parameters'] must be a dict with \"type\": \"OBJECT\".")

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return PluginRecord(name=name, file=filename,
                             error="Missing callable run(parameters, ...) function.")

    return PluginRecord(name=name, description=description.strip(), parameters=parameters,
                         run=run_fn, file=filename, valid=True, error="")


def load_plugin_file(path: Path, module_prefix: str = USER_PLUGINS_PREFIX) -> PluginRecord:
    """Import and validate a single plugin file. Never raises — returns a record."""
    try:
        module_name = f"{module_prefix}.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return PluginRecord(name=path.stem, file=path.name,
                                error="could not build import spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            sys.modules.pop(module_name, None)
            traceback.print_exc()
            return PluginRecord(name=path.stem, file=path.name,
                                error=f"Failed to load: {e}")
        return _validate(module, path.name)
    except Exception as e:
        return PluginRecord(name=path.stem, file=path.name, error=f"Failed to load: {e}")


def _ensure_package(directory: Path, module_prefix: str) -> None:
    """Make ``module_prefix`` importable (parent on sys.path + __init__.py) so
    relative imports inside plugin files resolve — also inside a frozen .app."""
    try:
        parent = str(directory.resolve().parent)
        if parent not in sys.path:
            sys.path.append(parent)
        init = directory / "__init__.py"
        if not init.exists():
            init.touch()  # best effort; a read-only dir just fails silently
    except OSError:
        pass


def _scan_dir(plugins_dir: Path, module_prefix: str, core_tool_names: set[str],
              logger, valid: dict, all_records: list) -> None:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    _ensure_package(plugins_dir, module_prefix)
    files = sorted(plugins_dir.glob("*.py"), key=lambda p: p.name)  # deterministic order
    for path in files:
        if path.name.startswith("_"):
            continue
        rec = load_plugin_file(path, module_prefix)

        if rec.valid and rec.name in core_tool_names:
            rec = PluginRecord(name=rec.name, file=path.name,
                                error=f"Name '{rec.name}' collides with a core tool — rejected.")
        elif rec.valid and rec.name in valid:
            other = valid[rec.name].file
            rec = PluginRecord(name=rec.name, file=path.name,
                                error=f"Name '{rec.name}' already used by plugin '{other}' — rejected.")

        all_records.append(rec)
        if rec.valid:
            valid[rec.name] = rec
            logger(f"Plugin loaded: {rec.name} ({path.name})")
        else:
            logger(f"Plugin rejected: {path.name} — {rec.error}")


def discover_plugins(plugins_dir: Path, core_tool_names: set[str],
                      logger: Callable[[str], None] = print,
                      extra_dirs: Optional[list[tuple[Path, str]]] = None) -> PluginRegistry:
    """
    Scans plugins_dir (bundled, module prefix ``plugins``) plus any extra user
    directories for *.py files (skips files starting with '_'). Import errors,
    validation errors, and name collisions are logged and the offending file is
    skipped — they NEVER raise out of this function and never abort the scan.
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, PluginRecord] = {}
    all_records: list[PluginRecord] = []

    _scan_dir(plugins_dir, "plugins", core_tool_names, logger, valid, all_records)
    for directory, prefix in (extra_dirs or []):
        _scan_dir(directory, prefix, core_tool_names, logger, valid, all_records)

    registry = PluginRegistry(valid, logger, core_tool_names)
    registry._all_records = all_records
    logger(f"Plugin discovery complete: {len(valid)} active, "
           f"{len(all_records) - len(valid)} rejected, {len(all_records)} total.")
    return registry
