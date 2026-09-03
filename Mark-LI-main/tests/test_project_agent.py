import shutil
import unittest
from pathlib import Path

from core.project_agent import AgentState, CommandPolicy, ProjectAgent


class ProjectAgentSmokeTests(unittest.TestCase):
    root = Path(__file__).resolve().parent / "_agent_smoke_workspace"

    def setUp(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_safe_edit_and_test_are_confined(self):
        agent = ProjectAgent(self.root, enabled=True, command_timeout=10)
        result = agent.handle({
            "operation": "execute",
            "goal": "write a small module",
            "edits": [{"path": "sample.py", "content": "value = 1\n"}],
            "tests": ["python -m py_compile sample.py"],
        })
        self.assertEqual(result.state, AgentState.IDLE)
        self.assertIn("passed", result.message)
        self.assertEqual((self.root / "sample.py").read_text(encoding="utf-8"), "value = 1\n")

    def test_risky_command_waits_for_exact_approval(self):
        agent = ProjectAgent(self.root, enabled=True)
        pending = agent.handle({
            "operation": "test",
            "tests": ["pip install example-package"],
        })
        self.assertEqual(pending.state, AgentState.AWAITING_APPROVAL)
        self.assertIsNotNone(pending.approval_id)
        different = agent.handle({
            "operation": "test",
            "tests": ["python -m unittest"],
            "confirmed": True,
        })
        self.assertEqual(different.state, AgentState.AWAITING_APPROVAL)
        direct = ProjectAgent(self.root, enabled=True).handle({
            "operation": "test",
            "tests": ["pip install example-package"],
            "confirmed": True,
        })
        self.assertEqual(direct.state, AgentState.AWAITING_APPROVAL)

    def test_policy_rejects_shell_and_escape_paths(self):
        policy = CommandPolicy()
        shell = policy.validate("python -c 'print(1)'", self.root, self.root)
        escape = policy.validate("python ../outside.py", self.root, self.root)
        self.assertFalse(shell.allowed)
        self.assertFalse(escape.allowed)

    def test_edits_outside_project_need_approval(self):
        project = self.root / "project"
        project.mkdir()
        agent = ProjectAgent(self.root, project_root=project, enabled=True)
        result = agent.handle({
            "operation": "execute",
            "edits": [{"path": "../notes.txt", "content": "approved later\n"}],
        })
        self.assertEqual(result.state, AgentState.AWAITING_APPROVAL)
        self.assertFalse((self.root / "notes.txt").exists())

    def test_pending_action_can_be_approved_or_rejected_from_ui(self):
        project = self.root / "project"
        project.mkdir()
        agent = ProjectAgent(self.root, project_root=project, enabled=True)
        pending = agent.handle({
            "operation": "execute",
            "edits": [{"path": "../approved.py", "content": "value = 2\n"}],
        })
        self.assertEqual(pending.state, AgentState.AWAITING_APPROVAL)
        self.assertTrue(agent.pending_request())
        rejected = agent.reject_pending()
        self.assertIn("rejected", rejected.message)
        self.assertFalse((self.root / "approved.py").exists())

        pending = agent.handle({
            "operation": "execute",
            "edits": [{"path": "../approved.py", "content": "value = 2\n"}],
        })
        self.assertEqual(pending.state, AgentState.AWAITING_APPROVAL)
        approved = agent.approve_pending()
        self.assertEqual(approved.state, AgentState.IDLE)
        self.assertTrue((self.root / "approved.py").exists())


if __name__ == "__main__":
    unittest.main()
