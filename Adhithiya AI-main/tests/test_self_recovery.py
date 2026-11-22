import json
import shutil
import time
import unittest
from pathlib import Path

from core.project_agent import CommandPolicy
from core.self_recovery import SelfRecovery, classify_obstacle


class SelfRecoveryTests(unittest.TestCase):
    root = Path(__file__).resolve().parent / "_recovery_workspace"

    def setUp(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        (self.root / "README.md").write_text(
            "Run `python -m py_compile sample.py` after a syntax failure.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_classifies_and_redacts_failure(self):
        failure = classify_obstacle(
            "project_agent", "Permission denied token=super-secret-value", "compile code"
        )
        self.assertEqual(failure.category, "permission")
        self.assertNotIn("super-secret", failure.message)
        self.assertEqual(len(failure.failure_signature), 16)

    def test_uses_local_doc_and_remembers_success(self):
        store = self.root / "recovery.json"
        recovery = SelfRecovery(
            self.root,
            enabled=True,
            max_attempts=2,
            timeout=2,
            store_path=store,
        )
        calls = []

        def execute(command):
            calls.append(command)
            return f"{command}: passed"

        result = recovery.recover(
            "project_agent",
            "SyntaxError in sample.py",
            goal="compile code",
            policy=CommandPolicy(),
            executor=execute,
        )
        self.assertEqual(result.status, "recovered")
        self.assertEqual(calls, ["python -m py_compile sample.py"])
        saved = json.loads(store.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["command"], "python -m py_compile sample.py")

        recovery.reset()
        self.assertFalse(store.exists())

    def test_risky_alternative_requires_exact_approval(self):
        recovery = SelfRecovery(self.root, max_attempts=2, timeout=2, store_path=self.root / "r.json")
        approvals = []
        result = recovery.recover(
            "project_agent",
            "No module named package",
            goal="install project dependencies",
            policy=CommandPolicy(),
            executor=lambda _command: "must not run",
            approval_callback=lambda candidate: approvals.append(candidate.command) or "approval-1",
        )
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(approvals, ["python -m pip install -r requirements.txt"])

    def test_attempts_and_timeout_are_bounded(self):
        recovery = SelfRecovery(self.root, max_attempts=1, timeout=1, store_path=self.root / "r.json")
        started = time.monotonic()
        result = recovery.recover(
            "project_agent",
            "test failed",
            goal="run tests",
            policy=CommandPolicy(),
            executor=lambda _command: time.sleep(5),
        )
        self.assertEqual(result.status, "exhausted")
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(result.attempts, 1)


if __name__ == "__main__":
    unittest.main()
