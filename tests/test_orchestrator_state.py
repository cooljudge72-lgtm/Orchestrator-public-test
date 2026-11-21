"""Synthetic-only tests for the T-003 fail-closed orchestration planner."""
import unittest

from orchestrator.state import Snapshot, transition

REPO = "cooljudge72-lgtm/Orchestrator-public-test"
A = "a" * 40
B = "b" * 40
C = "c" * 40


def step(s, event, head=None, actor="claude", **kw):
    return transition(s, event, repository=REPO, head_sha=head or s.head_sha,
                      actor=actor, claim_verified=True, **kw)


class StateTests(unittest.TestCase):
    def test_happy_path_never_merges(self):
        s = Snapshot(REPO, "T-003", A, "CLAIMED")
        s = step(s, "CLAIM_ACCEPTED", actor="owner")
        self.assertEqual(s.state, "IMPLEMENTING")
        s = step(s, "IMPLEMENTED", B)
        self.assertEqual(s.state, "REVIEWING")
        s = step(s, "REVIEW_APPROVED", actor="codex",
                 reviewer_independent=True, ci_passed=True)
        self.assertEqual(s.state, "READY_FOR_OWNER")
        self.assertEqual(step(s, "MERGE", actor="owner").state, "BLOCKED")

    def test_revision_cap(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        for i, head in enumerate((B, C)):
            s = step(s, "REVIEW_CHANGES", actor="codex",
                     reviewer_independent=True)
            self.assertEqual(s.revision_rounds, i + 1)
            s = step(s, "IMPLEMENTED", head)
        self.assertEqual(step(s, "REVIEW_CHANGES", actor="codex",
                              reviewer_independent=True).state, "BLOCKED")

    def test_stale_head_and_self_review_blocked(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(step(s, "REVIEW_APPROVED", B, actor="codex",
                              reviewer_independent=True, ci_passed=True).state, "BLOCKED")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="claude",
                              reviewer_independent=True, ci_passed=True).state, "BLOCKED")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="codex",
                              ci_passed=True).state, "BLOCKED")

    def test_unverified_claim_or_paths_or_repo_blocks(self):
        s = Snapshot(REPO, "T-003", A, "CLAIMED")
        self.assertEqual(transition(s, "CLAIM_ACCEPTED", repository=REPO,
                         head_sha=A, actor="owner").state, "BLOCKED")
        self.assertEqual(step(s, "CLAIM_ACCEPTED", actor="owner",
                              allowed_paths=False).state, "BLOCKED")
        self.assertEqual(transition(s, "CLAIM_ACCEPTED", repository="other/repo",
                         head_sha=A, actor="owner", claim_verified=True).state, "BLOCKED")

    def test_no_approval_without_ci(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="codex",
                              reviewer_independent=True).state, "BLOCKED")

    def test_same_head_implementation_rejected(self):
        s = Snapshot(REPO, "T-003", A, "IMPLEMENTING")
        self.assertEqual(step(s, "IMPLEMENTED").state, "BLOCKED")

    def test_blocked_is_terminal(self):
        s = Snapshot(REPO, "T-003", A, "BLOCKED")
        self.assertEqual(step(s, "CLAIM_ACCEPTED", actor="owner").state, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
