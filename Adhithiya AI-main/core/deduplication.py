"""Small in-memory guards against duplicate user requests and tool actions."""

from __future__ import annotations

import json
import time


class RecentRequestGuard:
    """Suppress an exact repeated user utterance inside a short time window."""

    def __init__(self, window_seconds: float = 2.5):
        self.window_seconds = max(0.0, float(window_seconds))
        self._last_text = ""
        self._last_time = 0.0

    @staticmethod
    def _normalize(text: object) -> str:
        return " ".join(str(text or "").casefold().split()).strip()

    def is_duplicate(self, text: object, now: float | None = None) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        current = time.monotonic() if now is None else float(now)
        if (normalized == self._last_text
                and current - self._last_time < self.window_seconds):
            return True
        self._last_text = normalized
        self._last_time = current
        return False


class ToolCallDeduplicator:
    """Cache one result per exact tool name/arguments within one chat turn."""

    @staticmethod
    def _key(name: object, arguments: object) -> str:
        try:
            canonical_args = json.dumps(
                arguments if isinstance(arguments, dict) else {},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
        except Exception:
            canonical_args = repr(arguments)
        return f"{str(name or '').strip()}:{canonical_args}"

    def __init__(self):
        self._results: dict[str, str] = {}

    def previous_result(self, name: object, arguments: object) -> str | None:
        return self._results.get(self._key(name, arguments))

    def remember(self, name: object, arguments: object, result: object) -> None:
        self._results[self._key(name, arguments)] = str(result or "")
