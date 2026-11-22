"""Small local adaptive-learning layer for explicit feedback and tool outcomes."""

from __future__ import annotations

import re
from datetime import datetime

from .memory_manager import load_memory, save_memory

_TEACHING_PATTERNS = (
    re.compile(r"^\s*(?:no|actually|correction|wrong)[,:]?\s+(.+)$", re.I),
    re.compile(r"^\s*(?:always|never|i prefer|please remember)\s+(.+)$", re.I),
)


def _entry(value: str, score: int = 1) -> dict:
    return {
        "value": value[:380],
        "score": score,
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }


def learn_from_user_text(text: str) -> bool:
    """Persist only explicit corrections/preferences; return whether learned."""
    if not isinstance(text, str):
        return False
    for pattern in _TEACHING_PATTERNS:
        match = pattern.match(text)
        if match:
            value = match.group(1).strip()
            if len(value) < 4:
                return False
            memory = load_memory()
            learning = memory.setdefault("learning", {})
            key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:60]
            learning[key or "instruction"] = _entry(value)
            save_memory(memory)
            return True
    return False


def record_tool_outcome(tool_name: str, success: bool) -> None:
    """Track lightweight tool reliability locally without storing user content."""
    if not tool_name:
        return
    memory = load_memory()
    learning = memory.setdefault("learning", {})
    key = f"tool_{tool_name}"
    current = learning.get(key, {})
    runs = int(current.get("runs", 0)) + 1
    successes = int(current.get("successes", 0)) + int(success)
    learning[key] = {
        "value": f"{successes}/{runs} successful",
        "runs": runs,
        "successes": successes,
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }
    save_memory(memory)


def format_learning_for_prompt(memory: dict | None) -> str:
    if not memory or not isinstance(memory.get("learning"), dict):
        return ""
    entries = []
    for key, item in memory["learning"].items():
        if not isinstance(item, dict) or not item.get("value"):
            continue
        if key.startswith("tool_"):
            continue
        entries.append(f"- {item['value']}")
    if not entries:
        return ""
    return (
        "[LEARNED USER GUIDANCE — follow when relevant, never recite]\n"
        + "\n".join(entries[-10:])
        + "\n"
    )
