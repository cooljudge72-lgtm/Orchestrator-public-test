import threading
import unittest

from lockcheck.lock import ACQUIRED, HELD, LockError, acquire, check_ref
from tests.fake_github import FakeGitHub, http_error

REPO, SHA = "example-owner/example-repo", "a" * 40


class TestLock(unittest.TestCase):
    def test_namespace_enforced(self):
        for bad in ("refs/heads/main", "refs/tags/v1", "refs/lockcheck/", "refs/lockcheck/a..b", "refs/lockcheck/a b"):
            with self.assertRaises(LockError, msg=bad):
                check_ref(bad)
        self.assertEqual(check_ref("refs/lockcheck/x-1"), "refs/lockcheck/x-1")

    def test_acquire_refuses_refs_outside_namespace_without_writing(self):
        gh = FakeGitHub()
        for bad in ("refs/heads/main", "refs/tags/v1", "refs/lockcheck/"):
            with self.assertRaises(LockError, msg=bad):
                acquire(gh, REPO, bad, SHA)
        self.assertEqual(gh.refs, {})

    def test_second_acquire_is_held(self):
        gh = FakeGitHub()
        self.assertEqual(acquire(gh, REPO, "refs/lockcheck/x", SHA), ACQUIRED)
        self.assertEqual(acquire(gh, REPO, "refs/lockcheck/x", SHA), HELD)

    def test_concurrent_acquire_has_one_winner(self):
        gh, results = FakeGitHub(), []
        threads = [threading.Thread(target=lambda: results.append(acquire(gh, REPO, "refs/lockcheck/x", SHA)))
                   for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((results.count(ACQUIRED), results.count(HELD)), (1, 19))

    def test_other_errors_fail_closed(self):
        for err in (http_error(422, "Validation Failed"), http_error(403, "Resource not accessible by integration")):
            gh = FakeGitHub()
            gh.create_error = err
            with self.assertRaises(LockError):
                acquire(gh, REPO, "refs/lockcheck/x", SHA)


if __name__ == "__main__":
    unittest.main()
