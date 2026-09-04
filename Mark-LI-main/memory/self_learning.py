"""Self-learning: research failed commands and remember how to fix them.

When a tool or command fails, ADHITHIYA searches the web for a solution,
distills the answer into short guidance with the LLM, stores it locally, and
feeds it back into the next session — so the same command succeeds later and
the knowledge is never lost.

Safety model
------------
This learns *knowledge* (text guidance) only. It never:
  * executes code or commands found online,
  * calls anything beyond the search provider and the configured LLM client,
  * stores secrets or raw credentials (errors are redacted),
  * talks over the user — the guidance is injected for the next response.

Storage: ``memory/learned_procedures.json`` (writable dir, so it survives
frozen .app builds). Each tool keeps its most recent distinct fixes, globally
capped to keep the prompt lean.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime

try:
    from .config_manager import get_data_dir, load_api_keys
except ImportError:  # pragma: no cover - safety fallback
    from memory.config_manager import get_data_dir, load_api_keys

LEARNED_PATH = get_data_dir() / "memory" / "learned_procedures.json"

_lock = threading.Lock()
MAX_ENTRIES = 40          # global cap on distinct tools
ISSUES_PER_TOOL = 5       # recent distinct fixes kept per tool
MAX_GUIDANCE_LEN = 1200

_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|bearer)"
    r"\b\s*[:=]?\s*[\w\-]{8,}"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _redact(value: object, limit: int = 400) -> str:
    """Strip ANSI codes and redact anything that looks like a credential."""
    text = _ANSI_RE.sub("", str(value or ""))
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text.strip()[:limit]


def _load() -> dict:
    if not LEARNED_PATH.exists():
        return {}
    try:
        data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        LEARNED_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo text search; [] on any failure (offline, rate-limited, …)."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


def _distill(tool_name: str, error: str, snippets: list[dict], api_key: str) -> str:
    """Turn search snippets into short, actionable guidance via the LLM."""
    try:
        from core.llm import chat
        context = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')[:300]}"
            for r in snippets[:6]
        )
        prompt = (
            f"The assistant tried to run the tool/command '{tool_name}' and it "
            f"failed with:\n  {error}\n\n"
            f"Web search results about the problem:\n{context or '(none)'}\n\n"
            "Write 2-4 short, concrete steps (in English) that would make this "
            "work, focusing on what to do differently. No intro, no filler, no "
            "apology. If the search results are irrelevant, answer from your own "
            "knowledge."
        )
        return chat([{"role": "user", "content": prompt}])["text"]
    except Exception as exc:  # noqa: BLE001 - learning must never crash the app
        print(f"[Learn] Distill failed: {exc}")
        return ""


def learn_from_failure(
    tool_name: str,
    args: dict | None,
    error: object,
    api_key: str | None = None,
) -> str:
    """Research a failure, store the fix, and return the guidance text.

    Returns "" when nothing useful was learned (no key, no network, no result).
    """
    if not tool_name:
        return ""
    if api_key is None:
        try:
            from core.llm import get_api_key
            api_key = get_api_key()
        except Exception:
            api_key = ""
    if not api_key:
        return ""

    error_clean = _redact(error, 300)
    if not error_clean:
        return ""

    snippets = _ddg_search(f"{tool_name} error {error_clean[:150]} how to fix")
    if not snippets:
        snippets = _ddg_search(f"how to fix {tool_name} {error_clean[:120]}")

    guidance = _distill(tool_name, error_clean, snippets, api_key)
    if not guidance:
        return ""

    data = _load()
    entry = data.get(tool_name)
    issues = entry.get("issues", []) if isinstance(entry, dict) else []

    # De-duplicate: replace an identical fix, keep the newest at the end.
    issues = [i for i in issues if i.get("guidance") != guidance]
    issues.append({
        "issue": error_clean[:200],
        "guidance": guidance[:MAX_GUIDANCE_LEN],
        "updated": datetime.now().strftime("%Y-%m-%d"),
    })

    data[tool_name] = {
        "issues": issues[-ISSUES_PER_TOOL:],
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }

    # Global prune so the injected prompt block never bloats.
    if len(data) > MAX_ENTRIES:
        for key in list(data)[:-MAX_ENTRIES]:
            del data[key]

    _save(data)
    print(f"[Learn] 🎓 Learned a fix for '{tool_name}'.")
    return guidance


def format_learned_for_prompt() -> str:
    """Return a compact block of learned procedures for the system prompt."""
    data = _load()
    if not data:
        return ""

    blocks: list[str] = []
    for tool, entry in list(data.items())[:8]:
        issues = entry.get("issues", []) if isinstance(entry, dict) else []
        if not issues:
            continue
        blocks.append(f"- {tool}: {issues[-1]['guidance'][:400]}")

    if not blocks:
        return ""

    return (
        "[LEARNED PROCEDURES — knowledge acquired from past failures. Apply it "
        "proactively when the situation matches; never recite it as a list]\n"
        + "\n".join(blocks)
        + "\n"
    )
