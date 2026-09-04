"""Autonomous task runner — ADHITHIYA's agentic core.

Given a single goal, this loops with the LLM: at each step the model either calls
one of a small set of *safe* tools or returns a final answer. The loop executes
the tool, feeds the result back, and repeats until the goal is done (or the step
budget runs out), then returns one concise summary for ADHITHIYA to speak.

This is what makes ADHITHIYA able to handle a whole multi-step job — "research X
and save a summary", "find the error in my project and fix it", "plan my week" —
instead of one tool call at a time.

Safety model
------------
The runner exposes a curated, side-effect-safe tool set only:

* web_search / web_fetch — read the web
* list_dir / read_file — read files (Desktop/Documents/Downloads/Pictures/workspace)
* write_file — writes ONLY inside the agent workspace (get_data_dir()/agent_workspace)
* run_command — a tiny allowlist (python, pytest, git, …) parsed without a shell,
  confined to the workspace, with destructive/network commands rejected
* set_reminder / list_calendar / add_note / search_notes — personal productivity
* generate_image — OpenAI image model, saved to ~/Pictures/ADHITHIYA/
* save_memory — long-term memory
* final_answer — ends the loop

Destructive or external actions (delete files, send messages, restart, …) are NOT
in this set, so the runner can never perform them — those still go through the
normal confirmation-gated tools.
"""

from __future__ import annotations

import os
import json
import shlex
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from memory.config_manager import get_data_dir
from core.project_agent import CommandPolicy

MAX_STEPS = 8
_COMMAND_TIMEOUT = 60

_SYSTEM = (
    "You are ADHITHIYA's autonomous task engine. You are given one GOAL. "
    "Break it into steps and use the available tools to accomplish it. "
    "After each tool result, decide the next step. When the goal is achieved — "
    "or clearly impossible — call final_answer with a clear, concise summary of "
    "what you did and the outcome. Use the fewest steps needed. Only report what "
    "the tools actually returned; never invent results. Never ask the user "
    "questions — just do the work and report. Use save_memory when you learn "
    "something worth keeping. Prefer web_search before claiming a fact you are "
    "unsure about."
)


def _workspace() -> Path:
    ws = get_data_dir() / "agent_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ── tool declarations for the model ───────────────────────────────────────────

_TOOL_SPECS: list[tuple[str, str, dict, list[str]]] = [
    ("web_search", "Search the web. query is required; mode is 'search' (default), 'news', 'research', 'price'.",
     {"query": "Search query.", "mode": "search | news | research | price"}, ["query"]),
    ("web_fetch", "Fetch a web page and return its key content as text.",
     {"url": "Full http(s) URL to fetch."}, ["url"]),
    ("list_dir", "List files/folders in a location. path: desktop | documents | downloads | pictures | workspace.",
     {"path": "desktop | documents | downloads | pictures | workspace"}, []),
    ("read_file", "Read a text file. path: desktop | documents | downloads | pictures | workspace; name: file name.",
     {"path": "Location keyword.", "name": "File name."}, ["name"]),
    ("write_file", "Write a text file INSIDE the agent workspace (safe area). Returns the saved path.",
     {"name": "File name (e.g. report.md).", "content": "Full file content."}, ["name", "content"]),
    ("run_command", "Run ONE safe developer command in the workspace (python, pytest, git, node, npm, …). No shell operators, no destructive/network commands.",
     {"command": "Single allowlisted command line."}, ["command"]),
    ("set_reminder", "Set a reminder. date=YYYY-MM-DD, time=HH:MM (24h), message=text.",
     {"date": "YYYY-MM-DD", "time": "HH:MM", "message": "Reminder text."}, ["date", "time", "message"]),
    ("list_calendar", "List upcoming macOS Calendar events.", {}, []),
    ("add_note", "Create a note in macOS Notes.",
     {"title": "Note title.", "body": "Note body."}, ["title"]),
    ("search_notes", "Search macOS Notes.",
     {"query": "Text to find."}, ["query"]),
    ("generate_image", "Generate an image from a prompt and save it to Pictures.",
     {"prompt": "Detailed image description."}, ["prompt"]),
    ("save_memory", "Remember something about the user (category, key, value).",
     {"category": "identity | preferences | notes | projects", "key": "Short key.", "value": "Value to store."},
     ["category", "key", "value"]),
    ("final_answer", "End the task with a concise summary of what was done and the outcome.",
     {"text": "The final summary."}, ["text"]),
]


def _declarations():
    """OpenAI-format tool objects for the agent loop."""
    tools = []
    for name, desc, props, required in _TOOL_SPECS:
        properties = {k: {"type": "string", "description": v} for k, v in props.items()}
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
    return tools


# ── safe tool implementations ─────────────────────────────────────────────────

_policy = CommandPolicy(allowed=CommandPolicy.DEFAULT_ALLOWED)

_KW_DIRS = {
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures": Path.home() / "Pictures",
}


def _write_file(name: str, content: str) -> str:
    safe = Path(name).name or "output.txt"
    path = _workspace() / safe
    path.write_text(content or "", encoding="utf-8")
    return f"Wrote {len(content or '')} chars to {path}."


def _list_dir(path: str) -> str:
    key = (path or "desktop").lower().strip()
    if key == "workspace":
        d = _workspace()
    else:
        d = _KW_DIRS.get(key)
        if d is None:
            return "Use path: desktop | documents | downloads | pictures | workspace."
    try:
        entries = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    except OSError as e:
        return f"Could not list {key}: {e}"
    return "\n".join(entries[:80]) or f"{key} is empty."


def _read_file(path: str, name: str) -> str:
    key = (path or "workspace").lower().strip()
    if key == "workspace":
        d = _workspace()
    else:
        d = _KW_DIRS.get(key)
        if d is None:
            return "Use path: desktop | documents | downloads | pictures | workspace."
    target = d / Path(name).name if name else None
    if target is None or not target.exists():
        return f"File not found in {key}: {name}"
    try:
        data = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Could not read {target}: {e}"
    return data[:4000]


def _run_command(command: str) -> str:
    ws = _workspace()
    decision = _policy.validate(command, ws, ws)
    if not decision.allowed:
        return f"Command not allowed: {decision.reason}"
    if decision.requires_approval:
        return f"Command needs approval: {decision.reason}"
    argv = list(decision.argv)
    if Path(argv[0]).name.lower() in {"python", "python3"}:
        argv[0] = sys.executable
    try:
        proc = subprocess.run(
            argv, cwd=str(ws), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_COMMAND_TIMEOUT, shell=False, check=False,
        )
    except subprocess.TimeoutExpired:
        return f"{command}: timed out after {_COMMAND_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        return f"Command failed: {e}"
    out = "\n".join(p for p in (proc.stdout.strip(), proc.stderr.strip()) if p)
    status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
    return f"{command}: {status}\n{(out or 'no output')[:1500]}"


def _dispatch(name: str, args: dict, player) -> str:
    try:
        if name == "web_search":
            from actions.web_search import web_search
            return web_search({"query": str(args.get("query", "")), "mode": str(args.get("mode", "search"))})
        if name == "web_fetch":
            from actions.web_fetch import web_fetch
            return web_fetch({"url": str(args.get("url", ""))})
        if name == "list_dir":
            return _list_dir(str(args.get("path", "desktop")))
        if name == "read_file":
            return _read_file(str(args.get("path", "workspace")), str(args.get("name", "")))
        if name == "write_file":
            return _write_file(str(args.get("name", "")), str(args.get("content", "")))
        if name == "run_command":
            return _run_command(str(args.get("command", "")))
        if name == "set_reminder":
            from actions.reminder import reminder
            return reminder({"date": str(args.get("date", "")), "time": str(args.get("time", "")),
                             "message": str(args.get("message", "Reminder"))})
        if name == "list_calendar":
            from plugins import mac_calendar
            return mac_calendar.run({"action": "list"}, player=player)
        if name == "add_note":
            from plugins import mac_notes
            return mac_notes.run({"action": "create", "title": str(args.get("title", "")),
                                  "body": str(args.get("body", ""))}, player=player)
        if name == "search_notes":
            from plugins import mac_notes
            return mac_notes.run({"action": "search", "query": str(args.get("query", ""))}, player=player)
        if name == "generate_image":
            from actions.image_generate import image_generate
            return image_generate({"prompt": str(args.get("prompt", ""))})
        if name == "save_memory":
            from memory.memory_manager import update_memory
            update_memory({str(args.get("category", "notes")): {str(args.get("key", "")): {"value": str(args.get("value", ""))}}})
            return "Saved to memory."
        if name == "final_answer":
            return str(args.get("text", "Done."))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return f"{name} failed: {e}"
    return f"Unknown tool '{name}'."


# ── the loop ──────────────────────────────────────────────────────────────────

def run_task(goal: str, player=None, api_key: str | None = None, max_steps: int = MAX_STEPS) -> str:
    goal = (goal or "").strip()
    if not goal:
        return "Give me a goal to work on."
    if api_key is None:
        try:
            from core.llm import get_api_key
            api_key = get_api_key()
        except Exception:
            api_key = ""
    if not api_key:
        return "No API key is configured, so I can't run a task autonomously."

    from core.llm import chat
    tools = _declarations()

    if player is not None and hasattr(player, "write_log"):
        player.write_log(f"[Agent] Goal: {goal[:120]}")

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"GOAL: {goal}"},
    ]
    final = ""

    for step in range(1, max_steps + 1):
        try:
            resp = chat(messages, tools=tools, temp=0.3)
        except Exception as e:  # noqa: BLE001
            return f"Task engine error on step {step}: {e}"

        calls = resp.get("tool_calls") or []
        if not calls:
            final = resp.get("text", "").strip()
            break

        # Execute every tool call requested this step, then append results.
        for tc in calls:
            name = tc.get("name", "")
            args = dict(tc.get("arguments") or {})
            result = _dispatch(name, args, player)
            if player is not None and hasattr(player, "write_log"):
                player.write_log(f"[Agent] step {step}: {name}")
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.get("id", f"call_{step}_{name}"),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{step}_{name}"),
                "content": result,
            })
            if name == "final_answer":
                final = str(args.get("text", "")).strip() or result

        if final:
            break
        if step == max_steps:
            final = (f"Ran {max_steps} steps; latest result: {str(messages[-1].get('content', ''))[:800]}")

    if not final:
        final = "I completed the task, but produced no summary."
    return final.strip()[:2500]
