import unittest

from lockcheck.verify import main, passed, run_check
from tests.fake_github import FakeGitHub, http_error

REPO, SHA = "example-owner/example-repo", "b" * 40


def good():
    return {"error": None, "results": ["acquired"] + ["held"] * 9, "points_at_commit": True,
            "cleanup": "deleted", "leftover": []}


class TestVerify(unittest.TestCase):
    def test_clean_run_passes_and_leaves_nothing(self):
        gh = FakeGitHub()
        report = run_check(gh, REPO, SHA, "t1")
        self.assertTrue(passed(report), report)
        self.assertEqual(gh.refs, {})

    def test_cleanup_failure_fails(self):
        gh = FakeGitHub()
        gh.delete_error = http_error(403, "Resource not accessible by integration")
        report = run_check(gh, REPO, SHA, "t2")
        self.assertIn("FAILED", report["cleanup"])
        self.assertFalse(passed(report))

    def test_lost_response_still_cleaned_up_and_fails(self):
        gh = FakeGitHub()
        gh.lose_response_once = True
        report = run_check(gh, REPO, SHA, "t3")
        self.assertFalse(passed(report))
        self.assertEqual(gh.refs, {})

    def test_read_back_failure_fails(self):
        gh = FakeGitHub()
        gh.read_error = http_error(500, "Server Error")
        self.assertFalse(passed(run_check(gh, REPO, SHA, "t4")))

    def test_each_criterion_is_required(self):
        self.assertTrue(passed(good()))
        for key, value in (("error", "x"), ("results", ["acquired", "acquired"] + ["held"] * 8),
                           ("results", ["acquired"] + ["held"] * 8), ("results", ["acquired"] + ["held"] * 8 + ["error: x"]),
                           ("points_at_commit", False), ("cleanup", "FAILED: HTTP 500"),
                           ("cleanup", "nothing to delete"), ("leftover", ["refs/lockcheck/x"]),
                           ("leftover", "unknown (HTTPError)")):
            bad = dict(good(), **{key: value})
            self.assertFalse(passed(bad), (key, value))

    def test_refuses_to_run_outside_manual_workflow(self):
        self.assertEqual(main(env={}), 2)
        self.assertEqual(main(env={"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push"}), 2)


if __name__ == "__main__":
    unittest.main()
