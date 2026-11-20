"""Task claims carry a verifiable execution identity and are atomic per task."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from lockcheck.claim import CLAIM_WORKFLOW, acquire_claim, build_identity, check_context, claim_ref, load_task, main
from lockcheck.lock import ACQUIRED, HELD, LockError
from tests.fake_github import FakeGitHub, http_error

REPO, OWNER, SHA = "example-owner/example-repo", "example-owner", "c" * 40
TASK = {"task_id": "T-001", "agent": "claude", "branch": "pilot/T-001",
        "allowed_paths": ["pilot/temperature.py"], "max_revision_rounds": 2}


def env(**over):
    base = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_OWNER": OWNER, "GITHUB_ACTOR": OWNER,
            "GITHUB_TRIGGERING_ACTOR": OWNER, "GITHUB_WORKFLOW_REF": f"{REPO}/{CLAIM_WORKFLOW}@refs/heads/main",
            "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "555", "GITHUB_RUN_ATTEMPT": "1", "TASK_ID": "T-001", "AGENT": "claude"}
    base.update(over)
    return base


def task_root():
    tmp = tempfile.TemporaryDirectory()
    (Path(tmp.name) / "tasks").mkdir()
    (Path(tmp.name) / "tasks" / "T-001.json").write_text(json.dumps(TASK))
    return tmp


class TestClaim(unittest.TestCase):
    def test_claim_ref_validates_task_id(self):
        self.assertEqual(claim_ref("T-001"), "refs/lockcheck/task-T-001")
        for bad in ("T-1", "t-001", "T-001/../x", "T-0011", "", None, "T-001 "):
            with self.assertRaises(LockError, msg=bad):
                claim_ref(bad)

    def test_identity_records_full_execution_context(self):
        ident = build_identity(env(), TASK)
        self.assertEqual(ident, {"task_id": "T-001", "agent": "claude", "repo": REPO, "actor": OWNER,
                                 "triggering_actor": OWNER, "workflow": CLAIM_WORKFLOW, "ref": "refs/heads/main",
                                 "sha": SHA, "run_id": "555", "run_attempt": "1"})

    def test_claim_is_atomic_and_identity_is_readable(self):
        gh, results = FakeGitHub(), []
        ident = build_identity(env(), TASK)
        threads = [threading.Thread(target=lambda: results.append(acquire_claim(gh, REPO, ident))) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((results.count(ACQUIRED), results.count(HELD)), (1, 9))
        ref = gh.call("GET", f"/repos/{REPO}/git/ref/lockcheck/task-T-001")
        self.assertEqual(ref["object"]["type"], "tag")
        self.assertEqual(json.loads(gh.tags[ref["object"]["sha"]])["run_id"], "555")

    def test_other_errors_fail_closed(self):
        gh = FakeGitHub()
        gh.create_error = http_error(403, "Resource not accessible by integration")
        with self.assertRaises(LockError):
            acquire_claim(gh, REPO, build_identity(env(), TASK))

    def test_context_must_be_owner_manual_main_claim_workflow(self):
        self.assertEqual(check_context(env(), "T-001", "claude", TASK), "")
        bad = [env(GITHUB_ACTIONS="false"), env(GITHUB_EVENT_NAME="push"), env(GITHUB_REF="refs/heads/pilot/T-001"),
               env(GITHUB_ACTOR="someone"), env(GITHUB_TRIGGERING_ACTOR="someone"),
               env(GITHUB_WORKFLOW_REF=f"{REPO}/.github/workflows/other.yml@refs/heads/main"),
               env(GITHUB_REPOSITORY_OWNER="")]
        for e in bad:
            self.assertNotEqual(check_context(e, "T-001", "claude", TASK), "", e)
        self.assertNotEqual(check_context(env(), "T-001", "codex", TASK), "")
        self.assertNotEqual(check_context(env(), "T-1", "claude", TASK), "")
        self.assertNotEqual(check_context(env(), "T-001", "claude", None), "")
        self.assertNotEqual(check_context(env(), "T-001", "claude", dict(TASK, task_id="T-002")), "")

    def test_main_claims_once_then_reports_held(self):
        gh, tmp = FakeGitHub(), task_root()
        with tmp:
            self.assertEqual(main(env(), gh=gh, root=tmp.name), 0)
            self.assertEqual(main(env(GITHUB_RUN_ID="556"), gh=gh, root=tmp.name), 1)
        self.assertEqual(list(gh.refs), ["refs/lockcheck/task-T-001"])

    def test_main_refuses_without_writing(self):
        gh, tmp = FakeGitHub(), task_root()
        with tmp:
            self.assertEqual(main(env(GITHUB_ACTOR="someone"), gh=gh, root=tmp.name), 2)
            self.assertEqual(main(env(TASK_ID="T-999"), gh=gh, root=tmp.name), 2)   # no task definition
        self.assertEqual((gh.refs, gh.tags), ({}, {}))

    def test_load_task_rejects_bad_ids(self):
        self.assertIsNone(load_task("../../etc/passwd"))
        self.assertIsNone(load_task("T-001", root="/nonexistent"))


if __name__ == "__main__":
    unittest.main()
