"""Self-authoring: ADHITHIYA writes its own plugins to gain new abilities.

When the user asks for something no existing tool or plugin covers, the
plugin_builder tool:

1. drafts a small, self-contained plugin with Gemini,
2. validates it — syntax, plugin contract, and a strict import allowlist —
   before the code is ever imported,
3. shows the user a preview (nothing runs yet), and
4. only after the user confirms writes it to ``~/.adhithiya/plugins/`` and
   hot-loads it into the running registry.

Because the plugin lives on disk and is re-discovered at every startup, a built
ability is *learned*: it persists across restarts and updates without any extra
prompting.

Safety model
------------
* Static scan before import: forbidden imports (subprocess/os/sys/shell/eval/
  network/secrets) and forbidden call patterns are rejected outright.
* Only a small import allowlist is permitted: the Python standard library, a
  couple of project helpers (memory.config_manager, memory.memory_manager), and
  the user's own Gemini client (google.genai).
* Nothing is written to disk or executed until the user confirms.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from memory.config_manager import load_api_keys
from core.plugin_loader import (
    USER_PLUGINS_DIR,
    USER_PLUGINS_PREFIX,
    load_plugin_file,
)

INDEX_PATH = USER_PLUGINS_DIR / "index.json"
_DRAFTS: dict[str, dict] = {}
_lock = threading.Lock()

# ── safety policy ─────────────────────────────────────────────────────────────

_ALLOWED_IMPORTS = {
    # stdlib
    "json", "re", "datetime", "pathlib", "textwrap", "unicodedata", "math",
    "statistics", "random", "time", "threading", "queue", "collections",
    "functools", "itertools", "string", "tempfile", "wave", "io", "csv",
    "html", "xml", "urllib.parse", "fractions", "decimal", "bisect", "heapq",
    "calendar", "zoneinfo", "difflib", "shlex",
    # project helpers
    "memory.config_manager", "memory.memory_manager",
    # the sanctioned AI channel (uses the user's own API key)
    "google.genai", "google.genai.types",
}
_ALLOWED_TOP = {"google"}          # subpath allowed for these (e.g. google.genai.types)

_FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "breakpoint", "input",
}
_TEXT_TRIPWIRES = (
    "subprocess", "os.system", "os.popen", "popen(", "shell=true",
    "requests.", "urllib.request", "socket.", "http.client",
    "eval(", "exec(", "__import__", "keyring", "getpass", "pickle.",
)

_GEN_MODEL = "gemini-flash-latest"


# ── helpers ───────────────────────────────────────────────────────────────────

def _api_key() -> str:
    try:
        return str(load_api_keys().get("gemini_api_key", "") or "")
    except Exception:
        return ""


def _slug_name(raw: object) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw or "").strip().lower()).strip("_")
    name = re.sub(r"_+", "_", name)
    if not name:
        return ""
    if not (name[0].isalpha() or name[0] == "_"):
        name = "p_" + name
    return name[:50]


def _strip_code(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*[ \t]*\n?", "", t)
        t = re.sub(r"\n?```[ \t]*$", "", t)
    return t.strip()


def _scan_source(source: str) -> str:
    """Return '' when the generated source passes the safety scan, else a reason."""
    src = (source or "").strip()
    if not src:
        return "empty plugin source"
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_TOP and alias.name not in _ALLOWED_IMPORTS:
                    return f"forbidden import '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                return "relative imports are not allowed"
            top = (node.module or "").split(".")[0]
            if top not in _ALLOWED_TOP and (node.module or "") not in _ALLOWED_IMPORTS:
                return f"forbidden import '{node.module}'"
            for alias in node.names:
                if alias.name == "*":
                    return "wildcard imports are not allowed"
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN_CALLS:
                return f"forbidden call '{fn.id}()'"
            if isinstance(fn, ast.Attribute) and fn.attr in _FORBIDDEN_CALLS:
                return f"forbidden call '.{fn.attr}()'"

    low = src.lower()
    for bad in _TEXT_TRIPWIRES:
        if bad in low:
            return f"forbidden pattern '{bad}'"
    return ""


def _generate(goal: str, name_hint: str, api_key: str) -> str:
    from google import genai
    client = genai.Client(api_key=api_key)
    prompt = (
        "You are writing ONE small Python plugin for ADHITHIYA, a macOS voice "
        "assistant. Output ONLY the Python code — no markdown fences, no commentary.\n\n"
        f"Goal of the new ability: {goal}\n"
        f"Suggested plugin name: {name_hint or 'your choice, snake_case'}\n\n"
        "The file MUST follow this exact contract:\n"
        "PLUGIN = {\n"
        '    "name": "<snake_case_identifier>",\n'
        '    "description": "<one English sentence: what it does and when to use it>",\n'
        '    "parameters": {\n'
        '        "type": "OBJECT",\n'
        '        "properties": {\n'
        '            "<param>": {"type": "STRING", "description": "<what it means>"}\n'
        "        },\n"
        '        "required": ["<param>"]\n'
        "    }\n"
        "}\n\n"
        "def run(parameters, player=None, session_memory=None):\n"
        "    '''Do the work and return a short, friendly plain-string result.'''\n"
        "    ...\n\n"
        "STRICT RULES:\n"
        "- Self-contained file; NO relative imports.\n"
        "- Imports allowed ONLY from: the Python standard library (json, re, datetime, "
        "pathlib, textwrap, math, random, time, threading, queue, collections, "
        "functools, itertools, string, tempfile, wave, io, csv, html, xml, "
        "urllib.parse, calendar, difflib, shlex, ...), these project helpers: "
        "memory.config_manager (get_data_dir, load_api_keys), memory.memory_manager, "
        "and google.genai / google.genai.types.\n"
        "- NEVER: subprocess, os, sys, shell, eval/exec/compile, __import__, "
        "requests/urllib.request/socket/http (no network except google.genai), "
        "reading environment variables, or reading credential/secret files.\n"
        "- Never read files outside get_data_dir(); never delete anything the user "
        "did not ask for.\n"
        "- macOS 12 compatible, pure Python, no third-party packages except google-genai.\n"
        "- No work at import time: only define PLUGIN and run().\n"
        "- Handle errors gracefully inside run() and return a message; never raise.\n"
        "- Keep it under ~120 lines and clear.\n"
    )
    resp = client.models.generate_content(model=_GEN_MODEL, contents=prompt)
    return (resp.text or "").strip()


def _validate_draft(code: str):
    """Import the code in a throwaway location to verify the plugin contract."""
    draft_dir = Path(tempfile.mkdtemp(prefix="adhithiya_draft_"))
    draft_file = draft_dir / "draft.py"
    draft_file.write_text(code, encoding="utf-8")
    return load_plugin_file(draft_file, "adhithiya_draft")


def _collision(registry, name: str) -> str:
    if registry.has(name):
        return (f"An ability named '{name}' already exists — use that one, or ask me "
                "to rebuild under a different name.")
    if name in getattr(registry, "_core_tool_names", ()):
        return f"'{name}' is a built-in ability name — I'll pick another. Ask me to try again."
    return ""


def _find_draft(name_hint: str, confirmed: bool) -> dict | None:
    with _lock:
        if name_hint and name_hint in _DRAFTS:
            return dict(_DRAFTS[name_hint])
        if confirmed and len(_DRAFTS) == 1:
            return dict(next(iter(_DRAFTS.values())))
    return None


def _install(name: str, code: str, registry, player) -> str:
    reason = _scan_source(code)
    if reason:
        return f"Safety check failed at install time ({reason}) — nothing was installed."
    USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    final = USER_PLUGINS_DIR / f"{name}.py"
    final.write_text(code, encoding="utf-8")

    rec = load_plugin_file(final, USER_PLUGINS_PREFIX)
    err = registry.register(rec)
    if err:
        try:
            final.unlink()
        except OSError:
            pass
        return f"I couldn't install '{name}': {err}"

    _index_add(name, rec.description)
    with _lock:
        _DRAFTS.pop(name, None)
    try:
        if player is not None and hasattr(player, "write_log"):
            player.write_log(f"New ability built and installed: {name}")
    except Exception:
        pass
    return (f"Installed new ability '{name}' — {rec.description}\n"
            f"It's live right now and saved to {final}.")


# ── index (the "learned abilities" record) ────────────────────────────────────

def _index_load() -> dict:
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _index_save(data: dict) -> None:
    try:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _index_add(name: str, description: str) -> None:
    data = _index_load()
    data[name] = {"description": description, "built": datetime.now().strftime("%Y-%m-%d")}
    _index_save(data)


def _list_built() -> str:
    data = _index_load()
    files = {p.stem for p in USER_PLUGINS_DIR.glob("*.py")} if USER_PLUGINS_DIR.exists() else set()
    if not files and not data:
        return ("I haven't built any new abilities yet. Tell me what you need and "
                "I'll write one for you.")
    lines = ["Built abilities:"]
    for name, meta in sorted(data.items()):
        lines.append(f"- {name}: {meta.get('description', '')}")
    for name in sorted(files - set(data)):
        lines.append(f"- {name} (no description recorded)")
    return "\n".join(lines)


# ── actions ───────────────────────────────────────────────────────────────────

def _build(parameters: dict, registry, player) -> str:
    goal = str(parameters.get("goal") or parameters.get("description") or "").strip()
    if not goal:
        return "Tell me what the new ability should do (goal), and I'll write it."
    confirmed = bool(parameters.get("confirmed"))
    name_hint = _slug_name(parameters.get("name"))

    draft = _find_draft(name_hint, confirmed)
    if draft is not None:
        name, code, desc = draft["name"], draft["code"], draft["description"]
    else:
        api_key = _api_key()
        if not api_key:
            return "No Gemini API key is configured, so I can't write a new ability."
        code = _strip_code(_generate(goal, name_hint, api_key))
        reason = _scan_source(code)
        if reason:
            return (f"My draft was rejected by the safety check ({reason}). "
                    "I'll rewrite it more safely — ask me to try again.")
        rec = _validate_draft(code)
        if not rec.valid:
            return f"My draft didn't pass validation: {rec.error}. I'll fix it — ask me to try again."
        err = _collision(registry, rec.name)
        if err:
            return err
        name, desc = rec.name, rec.description
        with _lock:
            _DRAFTS[name] = {
                "name": name, "code": code, "description": desc,
                "ts": datetime.now().isoformat(),
            }

    if not confirmed:
        return (f"I've drafted a new ability '{name}': {desc}\n"
                "It runs locally, uses no shell/network, and only activates once you "
                "approve. Say 'install it' (I'll rebuild with confirmed=true) to make "
                "it live.")

    return _install(name, code, registry, player)


def _remove(parameters: dict, registry, player) -> str:
    name = _slug_name(parameters.get("name"))
    if not name:
        return "Which ability should I remove? (give me its name)"
    if not parameters.get("confirmed"):
        return f"Confirm removing the built ability '{name}' with confirmed=true."
    path = USER_PLUGINS_DIR / f"{name}.py"
    if not path.exists():
        return f"I don't see a built ability named '{name}'."
    registry.unregister(name)
    try:
        path.unlink()
    except OSError as e:
        return f"Couldn't delete the file: {e}"
    data = _index_load()
    data.pop(name, None)
    _index_save(data)
    return f"Removed ability '{name}'."


def run(parameters: dict, registry, player=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = str(parameters.get("action", "build")).strip().lower().replace("-", "_").replace(" ", "_")
    if action in {"list", "status", "built"}:
        return _list_built()
    if action in {"remove", "delete", "uninstall"}:
        return _remove(parameters, registry, player)
    # default: build (aliases: build / install / create / add)
    return _build(parameters, registry, player)
