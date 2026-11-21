import unittest
from orchestrator.runtime_boundary import Decision, Review, validate_review, runtime_enabled

REPO = "cooljudge72-lgtm/Orchestrator-public-test"
SHA = "a" * 40

class RuntimeBoundaryTests(unittest.TestCase):
    def review(self, **changes):
        data = dict(repository=REPO, head_sha=SHA, reviewer="codex", decision=Decision.APPROVED)
        data.update(changes)
        return validate_review(Review(**data), repository=REPO, head_sha=SHA,
                               implementer="claude", allowed_reviewer="codex")

    def test_exact_independent_approval(self):
        self.assertEqual(self.review(), Decision.APPROVED)

    def test_stale_head_blocked(self):
        self.assertEqual(self.review(head_sha="b" * 40), Decision.BLOCKED)

    def test_wrong_repo_blocked(self):
        self.assertEqual(self.review(repository="private/judicial"), Decision.BLOCKED)

    def test_wrong_reviewer_blocked(self):
        self.assertEqual(self.review(reviewer="claude"), Decision.BLOCKED)

    def test_no_runtime_without_approval(self):
        self.assertFalse(runtime_enabled(explicit_owner_approval=False, implementer_ready=True,
            reviewer_ready=True, distinct_credentials=True, billing_approved=False,
            requires_paid_api=False))

    def test_paid_runtime_requires_billing_approval(self):
        self.assertFalse(runtime_enabled(explicit_owner_approval=True, implementer_ready=True,
            reviewer_ready=True, distinct_credentials=True, billing_approved=False,
            requires_paid_api=True))

    def test_separate_credentials_required(self):
        self.assertFalse(runtime_enabled(explicit_owner_approval=True, implementer_ready=True,
            reviewer_ready=True, distinct_credentials=False, billing_approved=True,
            requires_paid_api=True))

if __name__ == "__main__":
    unittest.main()
