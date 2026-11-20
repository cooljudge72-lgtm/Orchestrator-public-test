"""Static safety checks on the two workflows (no YAML library needed)."""
import re
import unittest
from pathlib import Path

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"
PINNED = re.compile(r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40}(\s|$)")


def code(name):
    """Workflow text without comment lines, so explanations cannot satisfy or break a check."""
    lines = (WF / name).read_text().splitlines()
    return "\n".join(l.split(" #", 1)[0] for l in lines if not l.lstrip().startswith("#")) + "\n"


class TestWorkflows(unittest.TestCase):
    def test_only_expected_workflows(self):
        names = sorted(p.name for p in WF.glob("*.y*ml"))
        self.assertIn("tests.yml", names)
        self.assertTrue(set(names) <= {"tests.yml", "verify-lock.yml"}, names)

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

    @unittest.skipUnless((WF / "verify-lock.yml").exists(), "verify-lock.yml is added in a later, approved step")
    def test_lock_workflow_is_manual_and_isolated(self):
        text = code("verify-lock.yml")
        on_block = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(on_block.strip(), "workflow_dispatch:")
        self.assertIn("\npermissions: {}\n", text)                    # nothing by default
        self.assertEqual(text.count("contents: write"), 1)            # only the one job
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("secrets.", text)

    def test_no_agent_workflows(self):
        for path in WF.glob("*.yml"):
            text = code(path.name).lower()
            for word in ("claude", "codex", "openai", "anthropic"):
                self.assertNotIn(word, text, f"{path.name} mentions {word}")


if __name__ == "__main__":
    unittest.main()
