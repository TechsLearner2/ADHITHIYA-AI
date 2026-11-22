"""Bounded, local-only recovery for project and plugin tool failures.

Recovery is deliberately conservative: it only runs commands that have already
passed the project's :class:`CommandPolicy`, never invokes a shell, and keeps
procedure memory separate from user conversation memory.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol


class CommandValidator(Protocol):
    def validate(self, command: str, cwd: Path, workspace_root: Path):
        ...


_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|bearer)"
    r"\b\s*(?:(?:=|:)\s*|\s+)([^\s,;]+)"
)
_LONG_SECRET_RE = re.compile(r"\b(?:AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,})\b")
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_COMMAND_RE = re.compile(
    r"(?<![\w-])((?:python3?|pytest|unittest|ruff|mypy|node|npm|git)"
    r"(?:\s+[^`\n\r;|&<>]{0,220})?)",
    re.IGNORECASE,
)
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"}
_DOC_NAMES = {
    "readme",
    "readme.md",
    "readme.txt",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "makefile",
    "tox.ini",
    "pytest.ini",
    "setup.cfg",
    "noxfile.py",
    "justfile",
}


def _redact(value: object, limit: int = 500) -> str:
    """Return bounded diagnostic text with likely credentials removed."""
    text = str(value or "")
    text = _SECRET_RE.sub(r"\1=<redacted>", text)
    text = _LONG_SECRET_RE.sub("<redacted>", text)
    text = _TOKEN_RE.sub("<redacted>", text)
    return text[:limit]


def _signature(*values: str) -> str:
    normalized = " ".join(" ".join(values).lower().split())
    return hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass(frozen=True)
class StructuredFailure:
    tool_name: str
    category: str
    message: str
    goal_signature: str
    failure_signature: str

    def as_dict(self) -> dict[str, str]:
        return {
            "tool": self.tool_name[:80],
            "category": self.category,
            "message": self.message,
            "goal_signature": self.goal_signature,
            "failure_signature": self.failure_signature,
        }


@dataclass(frozen=True)
class RecoveryCandidate:
    command: str
    source: str
    requires_approval: bool = False
    approval_reason: str = ""


@dataclass
class RecoveryResult:
    status: str
    failure: StructuredFailure
    attempts: int = 0
    messages: list[str] = field(default_factory=list)
    candidates: list[RecoveryCandidate] = field(default_factory=list)
    approval_id: str | None = None

    def as_text(self) -> str:
        if self.status == "recovered":
            return "Self-recovery succeeded. " + " ".join(self.messages[-2:])
        if self.status == "awaiting_approval":
            command = self.candidates[0].command if self.candidates else "the proposed recovery action"
            suffix = f" Approval id: {self.approval_id}." if self.approval_id else ""
            return f"Self-recovery needs exact approval for: {command}.{suffix}"
        if self.status == "disabled":
            return "Self-recovery is disabled."
        if self.status == "no_candidates":
            return "Self-recovery found no safe local procedure."
        return f"Self-recovery stopped after {self.attempts} bounded attempt(s)."


class ProcedureStore:
    """Small JSON store containing only reusable, redacted procedure metadata."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return []
        return data if isinstance(data, list) else []

    def successful_for(self, goal_signature: str, category: str) -> list[str]:
        with self._lock:
            entries = self._read()
        matching = [
            item.get("command")
            for item in entries
            if isinstance(item, dict)
            and item.get("goal_signature") == goal_signature
            and item.get("category") == category
            and isinstance(item.get("command"), str)
        ]
        return matching[:5]

    def record(self, goal_signature: str, category: str, command: str) -> None:
        safe_command = _redact(command, 300)
        if "<redacted>" in safe_command:
            return
        with self._lock:
            entries = self._read()
            for item in entries:
                if (
                    isinstance(item, dict)
                    and item.get("goal_signature") == goal_signature
                    and item.get("category") == category
                    and item.get("command") == safe_command
                ):
                    item["successes"] = int(item.get("successes", 0)) + 1
                    item["updated"] = datetime.now().strftime("%Y-%m-%d")
                    break
            else:
                entries.append({
                    "goal_signature": goal_signature,
                    "category": category,
                    "command": safe_command,
                    "successes": 1,
                    "updated": datetime.now().strftime("%Y-%m-%d"),
                })
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(entries[-100:], indent=2), encoding="utf-8")
            except OSError:
                # Recovery success must not become a project failure if memory is read-only.
                return

    def reset(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # Reset is best effort; status remains usable if the file is locked.
                return


def classify_obstacle(tool_name: str, error: object, goal: str = "") -> StructuredFailure:
    """Classify a failure without retaining its raw output or secrets."""
    message = _redact(error)
    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        category = "timeout"
    elif any(word in lowered for word in ("permission denied", "access denied", "not permitted")):
        category = "permission"
    elif any(word in lowered for word in ("no module named", "module not found", "not installed")):
        category = "missing_dependency"
    elif any(word in lowered for word in ("network", "connection", "dns", "certificate")):
        category = "network"
    elif any(word in lowered for word in ("syntaxerror", "test failed", "assertionerror", "exit 1")):
        category = "test_failure"
    elif "not found" in lowered or "no such file" in lowered:
        category = "missing_file"
    else:
        category = "unknown"
    goal_signature = _signature(_redact(goal, 300))
    return StructuredFailure(
        tool_name=_redact(tool_name, 80),
        category=category,
        message=message,
        goal_signature=goal_signature,
        failure_signature=_signature(tool_name, category, message),
    )


class SelfRecovery:
    """Search, validate, and execute a small number of safe alternatives."""

    def __init__(
        self,
        workspace_root: Path,
        project_root: Path | None = None,
        *,
        enabled: bool = True,
        max_attempts: int = 2,
        timeout: int = 30,
        store_path: Path | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if timeout < 1 or timeout > 300:
            raise ValueError("timeout must be between 1 and 300 seconds")
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_root = Path(project_root or workspace_root).expanduser().resolve()
        try:
            self.project_root.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("project_root must be inside workspace_root") from exc
        self.enabled = bool(enabled)
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.progress = progress
        self.store = ProcedureStore(
            store_path or self.workspace_root / "memory" / "recovery_procedures.json"
        )
        self._last: dict[str, object] = {"status": "idle", "attempts": 0}

    def _emit(self, text: str) -> None:
        if self.progress:
            self.progress(f"[Recovery] {text}")

    def status(self) -> dict[str, object]:
        return dict(self._last)

    def status_text(self) -> str:
        current = self.status()
        return (
            f"Self-recovery is {current.get('status', 'idle')} "
            f"(attempts: {current.get('attempts', 0)}/{self.max_attempts})."
        )

    def reset(self) -> None:
        self.store.reset()
        self._last = {"status": "idle", "attempts": 0}
        self._emit("status and learned procedures reset.")

    def recover(
        self,
        tool_name: str,
        error: object,
        *,
        goal: str = "",
        policy: CommandValidator,
        executor: Callable[[str], str],
        approval_callback: Callable[[RecoveryCandidate], str | None] | None = None,
        original_commands: Iterable[str] = (),
    ) -> RecoveryResult:
        failure = classify_obstacle(tool_name, error, goal)
        result = RecoveryResult("disabled", failure)
        self._last = {"status": "disabled", "attempts": 0, "failure": failure.as_dict()}
        if not self.enabled:
            return result

        candidates = self._candidates(failure, goal, policy, original_commands)
        result.candidates = candidates
        if not candidates:
            result.status = "no_candidates"
            self._last.update({"status": result.status, "attempts": 0})
            self._emit("no safe local alternative found.")
            return result

        for candidate in candidates:
            if candidate.requires_approval:
                result.status = "awaiting_approval"
                if approval_callback:
                    result.approval_id = approval_callback(candidate)
                self._last.update({
                    "status": result.status,
                    "attempts": result.attempts,
                    "approval_id": result.approval_id,
                })
                self._emit(f"approval required for exact command: {candidate.command}")
                return result
            if result.attempts >= self.max_attempts:
                break
            result.attempts += 1
            self._emit(f"trying safe alternative {result.attempts}/{self.max_attempts}: {candidate.command}")
            try:
                output = self._run_bounded(executor, candidate.command)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                output = _redact(exc)
            if _succeeded(output):
                result.status = "recovered"
                result.messages.append(f"{candidate.command} passed.")
                self.store.record(failure.goal_signature, failure.category, candidate.command)
                self._last.update({"status": result.status, "attempts": result.attempts})
                self._emit(f"recovered with {candidate.command}")
                return result
            result.messages.append(f"{candidate.command} did not resolve the obstacle.")

        result.status = "exhausted"
        self._last.update({"status": result.status, "attempts": result.attempts})
        self._emit(f"stopped after {result.attempts} bounded attempt(s).")
        return result

    def _run_bounded(self, executor: Callable[[str], str], command: str) -> str:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(executor, command)
        try:
            return str(future.result(timeout=self.timeout))
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise subprocess.TimeoutExpired(command, self.timeout)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _candidates(
        self,
        failure: StructuredFailure,
        goal: str,
        policy: CommandValidator,
        original_commands: Iterable[str],
    ) -> list[RecoveryCandidate]:
        commands: list[tuple[str, str]] = []
        for command in self.store.successful_for(failure.goal_signature, failure.category):
            commands.append((command, "learned procedure"))
        commands.extend(self._document_commands(goal, failure))
        commands.extend(self._default_commands(failure))
        seen: set[str] = set()
        original = set(original_commands)
        candidates: list[RecoveryCandidate] = []
        for command, source in commands:
            command = " ".join(command.strip().split())
            if (
                not command
                or "<redacted>" in command
                or _redact(command, 300) != command
                or command in seen
                or command in original
            ):
                continue
            seen.add(command)
            try:
                decision = policy.validate(command, self.project_root, self.workspace_root)
            except (OSError, ValueError, RuntimeError):
                continue
            if not decision.allowed:
                continue
            candidates.append(RecoveryCandidate(
                command=command,
                source=source,
                requires_approval=bool(decision.requires_approval),
                approval_reason=decision.reason,
            ))
            if len(candidates) >= self.max_attempts + 2:
                break
        return candidates

    def _document_commands(self, goal: str, failure: StructuredFailure) -> list[tuple[str, str]]:
        terms = set(_WORD_RE.findall(f"{goal} {failure.message}".lower()))
        if not terms:
            return []
        found: list[tuple[str, str]] = []
        files_seen = 0
        try:
            paths = self.workspace_root.rglob("*")
            for path in paths:
                if files_seen >= 100:
                    break
                if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
                    continue
                try:
                    if not path.resolve().is_relative_to(self.workspace_root):
                        continue
                except (OSError, RuntimeError):
                    continue
                if path.name.lower() not in _DOC_NAMES and path.suffix.lower() not in {
                    ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg"
                }:
                    continue
                try:
                    if path.stat().st_size > 200_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeError):
                    continue
                files_seen += 1
                for line in text.splitlines():
                    lower = line.lower()
                    if not any(term in lower for term in terms):
                        continue
                    for match in _COMMAND_RE.finditer(line):
                        command = match.group(1).strip().rstrip("`.,:)")
                        try:
                            shlex.split(command)
                        except ValueError:
                            continue
                        found.append((command, f"local docs: {path.name}"))
        except (OSError, RuntimeError):
            return found
        return found

    def _default_commands(self, failure: StructuredFailure) -> list[tuple[str, str]]:
        if failure.category == "missing_dependency":
            return [
                ("python -m pip install -r requirements.txt", "project dependency docs"),
                ("python -m pip install -r requirements-dev.txt", "project dependency docs"),
            ]
        if failure.category in {"test_failure", "syntax", "unknown"}:
            return [
                ("python -m pytest", "standard project test runner"),
                ("python -m unittest", "standard project test runner"),
            ]
        if failure.category == "timeout":
            return [("python -m pytest --collect-only", "bounded test discovery")]
        return []


def _succeeded(output: object) -> bool:
    text = str(output or "").lower()
    return "passed" in text and "failed" not in text and "error" not in text
