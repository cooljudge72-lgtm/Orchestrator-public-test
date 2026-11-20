"""Static safety checks on the workflows and on the code's write surface (no YAML library needed)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"
PINNED = re.compile(r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40}(\s|$)")
ALLOWED = {"tests.yml", "verify-lock.yml", "claim-task.yml", "pilot-status.yml"}
MANUAL_ONLY = ("verify-lock.yml", "claim-task.yml", "pilot-status.yml")


def code(name):
    """Workflow text without comment lines, so explanations cannot satisfy or break a check."""
    lines = (WF / name).read_text().splitlines()
    return "\n".join(l.split(" #", 1)[0] for l in lines if not l.lstrip().startswith("#")) + "\n"


def triggers(name):
    return code(name).split("\non:", 1)[1].split("\npermissions:", 1)[0]


class TestWorkflows(unittest.TestCase):
    def test_only_expected_workflows(self):
        names = {p.name for p in WF.glob("*.y*ml")}
        self.assertIn("tests.yml", names)
        self.assertTrue(names <= ALLOWED, names)

    def test_every_action_pinned_to_full_sha(self):
        for path in WF.glob("*.yml"):
            for line in path.read_text().splitlines():
                if "uses:" in line:
                    self.assertRegex(line.strip() + "\n", PINNED, f"{path.name}: {line.strip()}")

    def test_tests_workflow_is_read_only(self):
        text = code("tests.yml")
        self.assertNotIn("write", text)
        self.assertIn("contents: read", text)
        self.assertIn("persist-credentials: false", text)

    def test_privileged_workflows_are_manual_only(self):
        for name in MANUAL_ONLY:
            if (WF / name).exists():
                lines = [l.strip() for l in triggers(name).splitlines() if l.strip() and not l.startswith("      ")]
                self.assertEqual(lines[0], "workflow_dispatch:", name)
                self.assertNotRegex(triggers(name), r"(?m)^  (push|pull_request\w*|schedule|issues|issue_comment|workflow_run):")

    def test_contents_write_only_in_lock_and_claim(self):
        for path in WF.glob("*.yml"):
            text = code(path.name)
            count = text.count("contents: write")
            expected = 1 if path.name in ("verify-lock.yml", "claim-task.yml") else 0
            self.assertEqual(count, expected, path.name)
            if expected:
                self.assertIn("\npermissions: {}\n", text, path.name)       # nothing by default

    def test_nothing_can_merge_or_comment(self):
        for path in WF.glob("*.yml"):
            text = code(path.name)
            for perm in ("pull-requests: write", "issues: write", "actions: write", "checks: write", "statuses: write"):
                self.assertNotIn(perm, text, f"{path.name}: {perm}")
        for py in (ROOT / "lockcheck").glob("*.py"):
            src = py.read_text()
            self.assertNotRegex(src, r"/merge\b|\"PUT\"|'PUT'", py.name)

    @unittest.skipUnless((WF / "verify-lock.yml").exists(), "verify-lock.yml not present")
    def test_lock_workflow_is_isolated(self):
        text = code("verify-lock.yml")
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("secrets.", text)

    @unittest.skipUnless((WF / "claim-task.yml").exists(), "claim-task.yml not present")
    def test_claim_workflow_guards(self):
        text = code("claim-task.yml")
        for guard in ("github.ref == 'refs/heads/main'", "github.actor == github.repository_owner",
                      "github.triggering_actor == github.repository_owner", "persist-credentials: false",
                      "python -m lockcheck.claim"):
            self.assertIn(guard, text)
        self.assertNotIn("secrets.", text)

    @unittest.skipUnless((WF / "pilot-status.yml").exists(), "pilot-status.yml not present")
    def test_status_workflow_is_read_only(self):
        text = code("pilot-status.yml")
        self.assertNotIn("write", text)
        self.assertIn("python -m lockcheck.pilot_status", text)

    def test_inputs_never_interpolated_into_shell(self):
        for path in WF.glob("*.yml"):
            for line in code(path.name).splitlines():
                if line.strip().startswith("run:"):
                    self.assertNotRegex(line, r"\$\{\{\s*(inputs\.|github\.event\.)", f"{path.name}: {line.strip()}")

    def test_no_agent_actions(self):
        for path in WF.glob("*.yml"):
            text = code(path.name).lower()
            for action in ("anthropics/", "claude-code-action", "openai/", "codex-action", "secrets."):
                self.assertNotIn(action, text, f"{path.name} uses {action}")


if __name__ == "__main__":
    unittest.main()
