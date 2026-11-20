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
        self.assertEqual(json.loads(gh.tags[ref["object"]["sha"]]["message"])["run_id"], "555")

    def test_request_bodies_follow_the_documented_contract(self):
        gh = FakeGitHub()
        acquire_claim(gh, REPO, build_identity(env(), TASK))
        tag_req = next(b for m, p, b in gh.requests if p.endswith("/git/tags"))
        ref_req = next(b for m, p, b in gh.requests if p.endswith("/git/refs"))
        self.assertEqual(set(tag_req), {"tag", "message", "object", "type"})   # no optional tagger sent
        self.assertEqual((tag_req["tag"], tag_req["object"], tag_req["type"]), ("claim-T-001", SHA, "commit"))
        self.assertEqual(set(ref_req), {"ref", "sha"})
        self.assertEqual(ref_req["ref"], "refs/lockcheck/task-T-001")

    def test_tagger_in_response_is_optional(self):
        for with_tagger in (True, False):
            gh = FakeGitHub(tagger_in_response=with_tagger)
            self.assertEqual(acquire_claim(gh, REPO, build_identity(env(), TASK)), ACQUIRED)

    def test_malformed_tag_response_fails_before_creating_ref(self):
        good = {"sha": "1" * 40, "tag": "claim-T-001", "message": "", "object": {"type": "commit", "sha": SHA}}
        for bad in (None, {}, dict(good, sha="x"), dict(good, tag="claim-T-002"),
                    dict(good, object={"type": "commit", "sha": "d" * 40}), dict(good, object={"type": "tree", "sha": SHA})):
            gh = FakeGitHub()
            gh.tag_response_override = bad
            with self.assertRaises(LockError, msg=bad):
                acquire_claim(gh, REPO, build_identity(env(), TASK))
            self.assertEqual(gh.refs, {})

    def test_unconfirmed_ref_response_is_claim_state_unknown(self):
        for bad in ({}, {"ref": "refs/lockcheck/task-T-002", "object": {"type": "tag", "sha": "1" * 40}},
                    {"ref": "refs/lockcheck/task-T-001", "object": {"type": "commit", "sha": "1" * 40}}):
            gh = FakeGitHub()
            gh.ref_response_override = bad
            with self.assertRaises(LockError):
                acquire_claim(gh, REPO, build_identity(env(), TASK))

    def test_invalid_identity_sha_refused(self):
        with self.assertRaises(LockError):
            acquire_claim(FakeGitHub(), REPO, build_identity(env(GITHUB_SHA="main"), TASK))

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
