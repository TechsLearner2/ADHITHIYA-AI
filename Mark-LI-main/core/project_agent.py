"""A small, local, safety-first agent for working on the current project.

The Gemini Live session may suggest a plan, but this module is the authority
for what can be written or executed.  It never invokes a shell and every path
and command is checked before it reaches the operating system.
"""
from __future__ import annotations

import os
import re
import secrets
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .self_recovery import RecoveryCandidate, RecoveryResult, SelfRecovery


class AgentState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True)
class CommandDecision:
    """The result of validating a command without executing it."""

    allowed: bool
    requires_approval: bool
    reason: str
    argv: tuple[str, ...] = ()


@dataclass
class AgentResult:
    state: AgentState
    message: str
    progress: list[str] = field(default_factory=list)
    approval_id: str | None = None

    def as_text(self) -> str:
        if self.approval_id:
            return f"{self.message}\nApproval id: {self.approval_id}"
        return self.message


class CommandPolicy:
    """Allow a deliberately small set of developer commands.

    Commands are parsed with ``shlex`` and passed to ``subprocess`` as an argv
    list.  Shell syntax, shell interpreters, and inline-code flags are rejected
    rather than being made safe by quoting.
    """

    DEFAULT_ALLOWED = frozenset({
        "python", "python3", "pytest", "unittest", "ruff", "mypy",
        "node", "npm", "git",
    })
    HARD_DENIED = frozenset({
        "bash", "sh", "zsh", "fish", "cmd", "powershell", "pwsh",
        "sudo", "su", "ssh", "scp", "sftp", "nc", "netcat",
    })
    DESTRUCTIVE = frozenset({
        "rm", "rmdir", "del", "erase", "format", "shutdown", "reboot",
        "poweroff", "kill", "pkill", "killall", "chmod", "chown",
    })
    NETWORK_TOOLS = frozenset({"curl", "wget", "pip", "uv", "httpie"})
    SHELL_MARKERS = re.compile(r"[;&|<>`$\n\r]")

    def __init__(self, allowed: Iterable[str] | None = None):
        configured = allowed if allowed is not None else (
            self.DEFAULT_ALLOWED | self.DESTRUCTIVE | self.NETWORK_TOOLS
        )
        self.allowed = frozenset(str(item).lower() for item in configured)

    def validate(self, command: str, cwd: Path, workspace_root: Path) -> CommandDecision:
        if not isinstance(command, str) or not command.strip():
            return CommandDecision(False, False, "Command is empty.")
        if len(command) > 512:
            return CommandDecision(False, False, "Command is longer than 512 characters.")
        if self.SHELL_MARKERS.search(command):
            return CommandDecision(False, False, "Shell operators and multiline commands are not allowed.")
        try:
            argv = tuple(shlex.split(command, posix=os.name != "nt"))
        except ValueError as exc:
            return CommandDecision(False, False, f"Could not parse command: {exc}")
        if not argv:
            return CommandDecision(False, False, "Command is empty.")

        if "/" in argv[0] or "\\" in argv[0]:
            return CommandDecision(False, False, "Executable paths are not allowed; use an allowlisted command name.")
        executable = Path(argv[0]).name.lower()
        if executable in self.HARD_DENIED:
            return CommandDecision(False, False, f"'{executable}' is not permitted.")
        if executable not in self.allowed:
            return CommandDecision(False, False, f"'{executable}' is not in the agent command allowlist.")
        if any(flag in {"-c", "-e", "--eval", "--command"} for flag in argv[1:]):
            return CommandDecision(False, False, "Inline code and command-evaluation flags are not allowed.")
        if executable in {"python", "python3"} and "-m" in argv:
            module_index = argv.index("-m") + 1
            allowed_modules = {"pip", "py_compile", "pytest", "unittest", "ruff", "mypy"}
            if module_index >= len(argv) or argv[module_index].lower() not in allowed_modules:
                return CommandDecision(False, False, "That Python module is not allowed by the project policy.")

        try:
            cwd = cwd.resolve()
            workspace_root = workspace_root.resolve()
        except (OSError, RuntimeError) as exc:
            return CommandDecision(False, False, f"Could not resolve command boundary: {exc}")
        if not _is_within(cwd, workspace_root):
            return CommandDecision(False, False, "Command working directory is outside the workspace.")

        for token in argv[1:]:
            if token.lower().startswith(("http://", "https://")):
                continue
            # Resolve every value-like token, not only tokens with a slash:
            # a one-word symlink (for example, ``tests``) must not escape the
            # workspace either.
            if _looks_like_path(token) or not token.startswith("-"):
                try:
                    candidate = (
                        (cwd / token).resolve()
                        if not Path(token).is_absolute()
                        else Path(token).resolve()
                    )
                except (OSError, RuntimeError) as exc:
                    return CommandDecision(False, False, f"Could not resolve command path: {exc}")
                if not _is_within(candidate, workspace_root):
                    return CommandDecision(False, False, "Command references a path outside the workspace.")

        lower = [item.lower() for item in argv]
        destructive = executable in self.DESTRUCTIVE or (
            executable == "git" and any(item in {"reset", "clean", "checkout", "restore"} for item in lower[1:])
        ) or (
            executable in {"python", "python3"} and "pip" in lower and "uninstall" in lower
        )
        network = executable in self.NETWORK_TOOLS or (
            executable in {"git", "npm", "node"} and any(
                item in {"clone", "fetch", "pull", "push", "install", "uninstall", "publish", "add"} for item in lower[1:]
            )
        ) or (executable in {"python", "python3"} and "pip" in lower and "install" in lower)
        if destructive:
            return CommandDecision(True, True, "Destructive command requires explicit approval.", argv)
        if network:
            return CommandDecision(True, True, "Network or external command requires explicit approval.", argv)
        return CommandDecision(True, False, "Allowed project command.", argv)


class ProjectAgent:
    """Plan and apply project edits/tests inside a fixed workspace boundary."""

    def __init__(
        self,
        workspace_root: Path,
        project_root: Path | None = None,
        *,
        enabled: bool = True,
        command_policy: CommandPolicy | None = None,
        progress: Callable[[str], None] | None = None,
        command_timeout: int = 120,
        recovery: SelfRecovery | None = None,
    ):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_root = Path(project_root or workspace_root).expanduser().resolve()
        if not _is_within(self.project_root, self.workspace_root):
            raise ValueError("project_root must be inside workspace_root")
        if command_timeout < 1 or command_timeout > 900:
            raise ValueError("command_timeout must be between 1 and 900 seconds")
        self.enabled = bool(enabled)
        self.policy = command_policy or CommandPolicy()
        self.progress_callback = progress
        self.command_timeout = command_timeout
        self.state = AgentState.IDLE
        self._pending: tuple[str, dict] | None = None
        self.recovery = recovery or SelfRecovery(
            self.workspace_root,
            self.project_root,
            progress=progress,
        )

    def pending_request(self) -> dict | None:
        """Return a defensive copy of the request awaiting approval."""
        if self._pending is None:
            return None
        request = dict(self._pending[1])
        # Reconstruct the user-facing form so a subsequent ``handle`` call has
        # the same fingerprint as the original request.
        request["edits"] = [
            {
                "path": edit.get("display_path", edit.get("path", "")),
                "content": edit.get("content", ""),
            }
            for edit in request.get("edits", [])
        ]
        return request

    def reject_pending(self) -> AgentResult:
        """Reject and discard the currently pending request."""
        if self._pending is None:
            return AgentResult(self.state, "There is no project action awaiting approval.")
        approval_id, _request = self._pending
        self._pending = None
        self.state = AgentState.IDLE
        message = f"Project action {approval_id} rejected. No changes or commands were run."
        self._emit(message)
        return AgentResult(self.state, message, approval_id=approval_id)

    def approve_pending(self) -> AgentResult:
        """Approve the exact pending request, preserving normal policy checks."""
        request = self.pending_request()
        if request is None:
            return AgentResult(self.state, "There is no project action awaiting approval.")
        request["confirmed"] = True
        return self.handle(request)

    def status(self) -> AgentResult:
        return AgentResult(
            self.state,
            f"Project Agent is {self.state.value}. Workspace: {self.workspace_root}\n"
            f"{self.recovery.status_text()}",
        )

    def reset_recovery(self) -> AgentResult:
        """Clear recovery status and locally learned procedure metadata."""
        self.recovery.reset()
        self.state = AgentState.IDLE
        message = "Self-recovery status and learned procedures were reset."
        self._emit(message)
        return AgentResult(self.state, message)

    def recover_tool_failure(
        self,
        tool_name: str,
        error: object,
        *,
        goal: str = "",
        original_commands: Iterable[str] = (),
    ) -> RecoveryResult:
        """Try bounded local recovery for a failed project/plugin operation."""
        return self.recovery.recover(
            tool_name,
            error,
            goal=goal,
            policy=self.policy,
            executor=self._run_recovery_command,
            approval_callback=self._queue_recovery_approval,
            original_commands=original_commands,
        )

    def validate_path(self, value: str | os.PathLike[str], *, project_only: bool = False) -> Path:
        if not isinstance(value, (str, os.PathLike)):
            raise ValueError("Path must be a string.")
        raw = Path(value).expanduser()
        try:
            candidate = raw.resolve() if raw.is_absolute() else (self.project_root / raw).resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Could not resolve path '{value}': {exc}") from exc
        boundary = self.project_root if project_only else self.workspace_root
        if not _is_within(candidate, boundary):
            scope = "project" if project_only else "workspace"
            raise ValueError(f"Path '{value}' is outside the {scope} root.")
        return candidate

    def handle(self, parameters: Mapping[str, object] | None = None) -> AgentResult:
        params = dict(parameters or {})
        operation = str(params.get("operation", "execute")).strip().lower()
        if operation in {"reset", "recovery_reset"}:
            return self.reset_recovery()
        if not self.enabled:
            self.state = AgentState.IDLE
            return AgentResult(
                self.state,
                "Project work is paused right now.\n"
                + self.recovery.status_text(),
            )

        if operation == "status":
            return self.status()
        if operation == "recovery_status":
            return AgentResult(AgentState.IDLE, self.recovery.status_text())
        if operation not in {"plan", "execute", "test"}:
            return AgentResult(AgentState.IDLE, "Use operation: plan, execute, test, status, or reset.")

        try:
            request = self._normalise_request(params)
        except ValueError as exc:
            self.state = AgentState.IDLE
            return AgentResult(self.state, f"Project Agent rejected the request: {exc}")
        request["operation"] = operation

        if operation == "plan":
            self.state = AgentState.PLANNING
            message = self._plan_text(request)
            self._emit(message)
            return AgentResult(self.state, message)

        fingerprint = _fingerprint(request)
        confirmed = _is_confirmed(params)
        approved_pending = False
        if self._pending is not None:
            pending_id, pending_request = self._pending
            if fingerprint != _fingerprint(pending_request):
                self.state = AgentState.AWAITING_APPROVAL
                return AgentResult(
                    self.state,
                    "There is a different project action awaiting approval. "
                    "Repeat the exact request with confirmed=true.",
                    approval_id=pending_id,
                )
            if not confirmed:
                self.state = AgentState.AWAITING_APPROVAL
                return AgentResult(
                    self.state,
                    "This exact project action is still awaiting approval. "
                    "Reply with confirmed=true to continue.",
                    approval_id=pending_id,
                )
            self._pending = None
            approved_pending = True

        try:
            approval_reason = self._approval_reason(request, operation)
        except ValueError as exc:
            self.state = AgentState.IDLE
            return AgentResult(self.state, f"Project Agent rejected the request: {exc}")
        if approval_reason and not approved_pending:
            approval_id = secrets.token_urlsafe(9)
            self._pending = (approval_id, request)
            self.state = AgentState.AWAITING_APPROVAL
            message = f"Approval required: {approval_reason} No changes or commands were run."
            self._emit(message)
            return AgentResult(self.state, message, approval_id=approval_id)

        try:
            if request["external_actions"]:
                results = [
                    "External actions were recorded but not executed by the local agent: "
                    + ", ".join(request["external_actions"])
                ]
            else:
                results = []
            if operation == "test":
                results.extend(self._run_tests(request["tests"], request["goal"]))
            else:
                self.state = AgentState.PLANNING
                self._emit(self._plan_text(request))
                results.extend(self._execute(request))
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            self.state = AgentState.IDLE
            message = f"Project Agent stopped safely: {exc}"
            self._emit(message)
            return AgentResult(self.state, message)

        if self.state == AgentState.AWAITING_APPROVAL:
            message = "Project Agent paused for recovery approval.\n" + "\n".join(results)
            self._emit(message)
            return AgentResult(
                self.state,
                message,
                progress=results,
                approval_id=self._pending[0] if self._pending else None,
            )
        self.state = AgentState.IDLE
        message = "Project Agent completed.\n" + "\n".join(results)
        self._emit(message)
        return AgentResult(self.state, message, progress=results)

    def _normalise_request(self, params: Mapping[str, object]) -> dict:
        goal = str(params.get("goal", "") or "").strip()
        edits = _as_list(params.get("edits"))
        commands = _as_strings(params.get("commands"))
        tests = _as_strings(params.get("tests"))
        external = _as_strings(params.get("external_actions"))
        if not goal and not edits and not commands and not tests and not external:
            raise ValueError("Provide a goal, edits, commands, or tests.")

        normalised_edits: list[dict[str, str]] = []
        for item in edits:
            if not isinstance(item, Mapping):
                raise ValueError("Each edit must be an object with path and content.")
            path = item.get("path")
            content = item.get("content")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("Each edit needs a relative path.")
            if not isinstance(content, str):
                raise ValueError(f"Edit '{path}' needs string content.")
            resolved = self.validate_path(path)
            normalised_edits.append({"path": str(resolved), "display_path": path, "content": content})

        # Validate all command syntax before any action is performed.
        for command in commands + tests:
            decision = self.policy.validate(command, self.project_root, self.workspace_root)
            if not decision.allowed:
                raise ValueError(decision.reason)
        if external:
            # External actions are descriptions only; this local agent never
            # sends messages, opens URLs, or invokes another application.
            external = [item[:300] for item in external]
        return {
            "goal": goal[:1000],
            "edits": normalised_edits,
            "commands": commands,
            "tests": tests,
            "external_actions": external,
        }

    def _approval_reason(self, request: dict, operation: str) -> str | None:
        reasons: list[str] = []
        for command in request["commands"] + request["tests"]:
            decision = self.policy.validate(command, self.project_root, self.workspace_root)
            if decision.requires_approval:
                reasons.append(f"'{command}' ({decision.reason.lower()})")
        outside_project = [
            edit["display_path"] for edit in request["edits"]
            if not _is_within(Path(edit["path"]), self.project_root)
        ]
        if outside_project:
            reasons.append("file edits outside the project root: " + ", ".join(outside_project))
        if request["external_actions"]:
            reasons.append("external actions: " + ", ".join(request["external_actions"]))
        if reasons:
            return "; ".join(reasons)
        return None

    def _plan_text(self, request: dict) -> str:
        edits = ", ".join(item["display_path"] for item in request["edits"]) or "none"
        commands = ", ".join(request["commands"]) or "none"
        tests = ", ".join(request["tests"]) or "none"
        return (
            f"Plan for {request['goal'] or 'the requested project work'}:\n"
            f"- Workspace: {self.workspace_root}\n"
            f"- Edits: {edits}\n"
            f"- Commands: {commands}\n"
            f"- Tests: {tests}\n"
            "No files or commands were changed during planning."
        )

    def _execute(self, request: dict) -> list[str]:
        self.state = AgentState.EXECUTING
        self._emit("Executing approved project actions.")
        results: list[str] = []
        for edit in request["edits"]:
            target = Path(edit["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit["content"], encoding="utf-8")
            message = f"Edited {edit['display_path']}"
            results.append(message)
            self._emit(message)
        for command in request["commands"]:
            results.extend(self._run_with_recovery(command, request["goal"]))
            if self.state == AgentState.AWAITING_APPROVAL:
                return results
        if request["tests"]:
            results.extend(self._run_tests(request["tests"], request["goal"]))
        return results or ["No execution actions were supplied."]

    def _run_tests(self, tests: Sequence[str], goal: str = "") -> list[str]:
        self.state = AgentState.TESTING
        self._emit("Testing project changes.")
        results: list[str] = []
        for command in tests:
            results.extend(self._run_with_recovery(command, goal))
            if self.state == AgentState.AWAITING_APPROVAL:
                break
        return results or ["No tests were supplied."]

    def _run_with_recovery(self, command: str, goal: str) -> list[str]:
        output = self._run_command(command)
        results = [output]
        if _command_failed(output):
            recovery = self.recover_tool_failure(
                "project_agent",
                output,
                goal=goal,
                original_commands=(command,),
            )
            if recovery.status != "no_candidates":
                results.append(recovery.as_text())
        return results

    def _queue_recovery_approval(self, candidate: RecoveryCandidate) -> str:
        approval_id = secrets.token_urlsafe(9)
        request = {
            "operation": "test",
            "goal": "approved self-recovery procedure",
            "edits": [],
            "commands": [],
            "tests": [candidate.command],
            "external_actions": [],
        }
        self._pending = (approval_id, request)
        self.state = AgentState.AWAITING_APPROVAL
        return approval_id

    def _run_recovery_command(self, command: str) -> str:
        return self._run_command(command, timeout=min(self.command_timeout, self.recovery.timeout))

    def _run_command(self, command: str, *, timeout: int | None = None) -> str:
        decision = self.policy.validate(command, self.project_root, self.workspace_root)
        if not decision.allowed:
            raise ValueError(decision.reason)
        self._emit(f"Running: {command}")
        argv = list(decision.argv)
        if Path(argv[0]).name.lower() in {"python", "python3"}:
            argv[0] = sys.executable
        try:
            completed = subprocess.run(
                argv,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.command_timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"{command}: timed out after {timeout or self.command_timeout}s"
        output = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        summary = output[:1200] if output else "no output"
        status = "passed" if completed.returncode == 0 else f"failed (exit {completed.returncode})"
        return f"{command}: {status}\n{summary}"

    def _emit(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _looks_like_path(token: str) -> bool:
    return (
        token in {".", ".."}
        or token.startswith(("/", "./", "../", "~", "\\"))
        or "/" in token
        or "\\" in token
        or bool(re.match(r"^[A-Za-z]:", token))
        or token.endswith((".py", ".js", ".ts", ".json", ".toml", ".yml", ".yaml"))
    )


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("Expected a list.")
    return list(value)


def _as_strings(value: object) -> list[str]:
    items = _as_list(value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise ValueError("Command and action lists must contain non-empty strings.")
    return [item.strip() for item in items]


def _is_confirmed(params: Mapping[str, object]) -> bool:
    value = params.get("confirmed", False)
    return value is True or str(value).strip().lower() in {"true", "yes", "1", "confirm"}


def _fingerprint(request: Mapping[str, object]) -> str:
    return repr(sorted((str(key), repr(value)) for key, value in request.items()))


def _command_failed(output: str) -> bool:
    lowered = str(output).lower()
    return (
        ": failed" in lowered
        or ": timed out" in lowered
        or lowered.startswith(("failed", "error", "timed out"))
    )
