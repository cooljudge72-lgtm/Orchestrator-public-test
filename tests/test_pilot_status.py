"""Fail-closed pilot status: claim identity, allowed files, unittest on head, owner verdict on head."""
import base64
import copy
import json
import unittest

from lockcheck.pilot_status import (BLOCKED, NEEDS_REVIEW, NEEDS_REVISION, READY, WAITING, evaluate,
                                    fetch_facts, main, parse_verdicts)
from tests.fake_github import FakeGitHub, http_error

REPO, OWNER = "example-owner/example-repo", "example-owner"
HEAD, OLD = "a" * 40, "b" * 40
TASK = {"task_id": "T-001", "agent": "claude", "branch": "pilot/T-001",
        "allowed_paths": ["pilot/__init__.py", "pilot/temperature.py", "tests/test_temperature.py"],
        "max_revision_rounds": 2}
META = {"task_id": "T-001", "agent": "claude", "repo": REPO, "actor": OWNER, "triggering_actor": OWNER,
        "workflow": ".github/workflows/claim-task.yml", "ref": "refs/heads/main", "sha": "c" * 40,
        "run_id": "555", "run_attempt": "1"}
RUN = {"id": 555, "repository": {"full_name": REPO}, "path": ".github/workflows/claim-task.yml",
       "event": "workflow_dispatch", "actor": {"login": OWNER}, "triggering_actor": {"login": OWNER},
       "head_branch": "main", "run_attempt": 1, "status": "completed", "conclusion": "success",
       "created_at": "2026-11-21T09:00:00Z"}


def verdict_comment(cid, sha, verdict, login=OWNER, assoc="OWNER", edited=False, task="T-001", extra=""):
    created = f"2026-11-21T10:{cid:02d}:00Z"
    return {"id": cid, "user": {"login": login}, "author_association": assoc, "created_at": created,
            "updated_at": "2026-11-21T11:59:59Z" if edited else created,
            "body": f"CODEX-REVIEW {task} {sha} {verdict}{extra}\n\nFindings: synthetic."}


def facts(**over):
    f = {"owner": OWNER, "repo": REPO, "task": copy.deepcopy(TASK),
         "pr": {"number": 2, "state": "open", "merged": False, "created_at": "2026-11-21T09:30:00Z",
                "head": {"ref": "pilot/T-001", "sha": HEAD, "repo": {"full_name": REPO}}, "base": {"ref": "main"}},
         "claim": {"type": "tag", "meta": copy.deepcopy(META)}, "claim_run": copy.deepcopy(RUN),
         "files": ["pilot/temperature.py", "tests/test_temperature.py"],
         "checks": [{"id": 10, "name": "unittest", "app": "github-actions", "head_sha": HEAD,
                     "status": "completed", "conclusion": "success"}],
         "comments": [verdict_comment(1, HEAD, "APPROVED")]}
    f.update(over)
    return f


def v(f):
    return evaluate(f)[0]


class TestReady(unittest.TestCase):
    def test_all_conditions_met(self):
        verdict, reasons, details = evaluate(facts())
        self.assertEqual(verdict, READY, reasons)
        self.assertEqual(details["head"], HEAD)


class TestClaimIdentity(unittest.TestCase):
    def test_missing_or_untyped_claim(self):
        for claim in (None, {"type": "commit"}, {"type": "tag"}, {"type": "tag", "meta": "x"}):
            self.assertEqual(v(facts(claim=claim)), BLOCKED, claim)

    def test_each_identity_field_is_checked(self):
        for key, bad in (("task_id", "T-002"), ("agent", "codex"), ("repo", "other/repo"), ("actor", "x"),
                         ("triggering_actor", "x"), ("workflow", ".github/workflows/x.yml"),
                         ("ref", "refs/heads/pilot/T-001"), ("run_id", "abc"), ("run_attempt", "x")):
            f = facts()
            f["claim"]["meta"][key] = bad
            self.assertEqual(v(f), BLOCKED, key)

    def test_claim_run_must_match_the_actions_api(self):
        for key, bad in (("id", 556), ("repository", {"full_name": "other/repo"}), ("path", ".github/workflows/x.yml"),
                         ("event", "push"), ("actor", {"login": "x"}), ("triggering_actor", {"login": "x"}),
                         ("head_branch", "pilot/T-001"), ("run_attempt", 2), ("status", "in_progress"),
                         ("conclusion", "failure"), ("created_at", "2026-11-21T09:45:00Z")):
            f = facts()
            f["claim_run"][key] = bad
            self.assertEqual(v(f), BLOCKED, key)
        self.assertEqual(v(facts(claim_run=None)), BLOCKED)

    def test_rest_style_run_path_accepted(self):
        f = facts()
        f["claim_run"]["path"] = f"{REPO}/.github/workflows/claim-task.yml@refs/heads/main"
        self.assertEqual(v(f), READY)


class TestPullRequestAndFiles(unittest.TestCase):
    def test_pr_integrity(self):
        for key, value in (("state", "closed"), ("merged", True), ("base", {"ref": "release"})):
            f = facts()
            f["pr"][key] = value
            self.assertEqual(v(f), BLOCKED, key)
        for head in ({"ref": "feature/x", "sha": HEAD, "repo": {"full_name": REPO}},
                     {"ref": "pilot/T-001", "sha": HEAD, "repo": {"full_name": "fork/repo"}},
                     {"ref": "pilot/T-001", "sha": "short", "repo": {"full_name": REPO}}):
            f = facts()
            f["pr"]["head"] = head
            self.assertEqual(v(f), BLOCKED, head)

    def test_task_definition_required(self):
        self.assertEqual(v(facts(task=None)), BLOCKED)
        self.assertEqual(v(facts(task=dict(TASK, branch="pilot/T-002"))), BLOCKED)
        self.assertEqual(v(facts(task=dict(TASK, max_revision_rounds=True))), BLOCKED)

    def test_files_outside_allowed_paths_block(self):
        for extra in (".github/workflows/tests.yml", "lockcheck/lock.py", "tasks/T-001.json", "README.md"):
            self.assertEqual(v(facts(files=["pilot/temperature.py", extra])), BLOCKED, extra)
        self.assertEqual(v(facts(files=[])), BLOCKED)
        self.assertEqual(v(facts(files=None)), BLOCKED)


class TestChecks(unittest.TestCase):
    def test_check_states(self):
        self.assertEqual(v(facts(checks=[])), WAITING)
        running = [{"id": 10, "name": "unittest", "app": "github-actions", "head_sha": HEAD,
                    "status": "in_progress", "conclusion": None}]
        self.assertEqual(v(facts(checks=running)), WAITING)
        failed = [dict(running[0], status="completed", conclusion="failure")]
        self.assertEqual(v(facts(checks=failed)), NEEDS_REVISION)

    def test_only_latest_actions_check_on_head_counts(self):
        ok = {"id": 10, "name": "unittest", "app": "github-actions", "head_sha": HEAD, "status": "completed",
              "conclusion": "success"}
        self.assertEqual(v(facts(checks=[ok, dict(ok, id=11, conclusion="failure")])), NEEDS_REVISION)
        self.assertEqual(v(facts(checks=[dict(ok, app="other-app")])), WAITING)
        self.assertEqual(v(facts(checks=[dict(ok, head_sha=OLD)])), WAITING)


class TestVerdicts(unittest.TestCase):
    def test_no_verdict_needs_review(self):
        self.assertEqual(v(facts(comments=[])), NEEDS_REVIEW)

    def test_stale_approval_is_void_after_new_commit(self):
        self.assertEqual(v(facts(comments=[verdict_comment(1, OLD, "APPROVED")])), NEEDS_REVIEW)

    def test_latest_verdict_wins(self):
        self.assertEqual(v(facts(comments=[verdict_comment(1, HEAD, "APPROVED"),
                                           verdict_comment(2, HEAD, "CHANGES_REQUESTED")])), NEEDS_REVISION)
        self.assertEqual(v(facts(comments=[verdict_comment(1, HEAD, "CHANGES_REQUESTED"),
                                           verdict_comment(2, HEAD, "APPROVED")])), READY)

    def test_only_owner_unedited_exact_markers_count(self):
        for bad in (verdict_comment(1, HEAD, "APPROVED", login="someone", assoc="NONE"),
                    verdict_comment(1, HEAD, "APPROVED", assoc="CONTRIBUTOR"),
                    verdict_comment(1, HEAD, "APPROVED", edited=True),
                    verdict_comment(1, HEAD, "APPROVED", task="T-002"),
                    verdict_comment(1, HEAD, "APPROVED", extra=" please"),
                    verdict_comment(1, HEAD, "approved"),
                    dict(verdict_comment(1, HEAD, "APPROVED"), body="LGTM\nCODEX-REVIEW T-001 " + HEAD + " APPROVED")):
            self.assertEqual(v(facts(comments=[bad])), NEEDS_REVIEW, bad["body"][:60])

    def test_outsider_cannot_override_owner_verdict(self):
        comments = [verdict_comment(1, HEAD, "CHANGES_REQUESTED"),
                    verdict_comment(2, HEAD, "APPROVED", login="someone", assoc="NONE")]
        self.assertEqual(v(facts(comments=comments)), NEEDS_REVISION)

    def test_revision_rounds_are_capped(self):
        shas = ["1" * 40, "2" * 40, "3" * 40]
        two = [verdict_comment(i + 1, s, "CHANGES_REQUESTED") for i, s in enumerate(shas[:2])]
        self.assertEqual(v(facts(comments=two + [verdict_comment(5, HEAD, "APPROVED")])), READY)
        three = [verdict_comment(i + 1, s, "CHANGES_REQUESTED") for i, s in enumerate(shas)]
        self.assertEqual(v(facts(comments=three + [verdict_comment(5, HEAD, "APPROVED")])), BLOCKED)

    def test_parse_orders_by_time(self):
        parsed = parse_verdicts([verdict_comment(3, HEAD, "APPROVED"), verdict_comment(1, OLD, "CHANGES_REQUESTED")],
                                OWNER, "T-001")
        self.assertEqual([p["id"] for p in parsed], [1, 3])


class TestFetchAndMain(unittest.TestCase):
    def gh_with_routes(self):
        gh = FakeGitHub()
        f = facts()
        tag_sha = "f" * 40
        gh.tags[tag_sha] = json.dumps(META)
        gh.refs["refs/lockcheck/task-T-001"] = tag_sha
        gh.routes.update({
            f"/repos/{REPO}/pulls/2": f["pr"],
            f"/repos/{REPO}/contents/tasks/T-001.json?ref=main": {"content": base64.b64encode(json.dumps(TASK).encode()).decode()},
            f"/repos/{REPO}/pulls/2/files?per_page=100&page=1": [{"filename": x} for x in f["files"]],
            f"/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100": {"check_runs": [
                {"id": 10, "name": "unittest", "status": "completed", "conclusion": "success", "head_sha": HEAD,
                 "app": {"slug": "github-actions"}}]},
            f"/repos/{REPO}/issues/2/comments?per_page=100&page=1": f["comments"],
            f"/repos/{REPO}/actions/runs/555": RUN})
        return gh

    def env(self, **over):
        e = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
             "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_OWNER": OWNER, "GITHUB_ACTOR": OWNER, "PR_NUMBER": "2"}
        e.update(over)
        return e

    def test_fetch_then_evaluate_ready(self):
        self.assertEqual(evaluate(fetch_facts(self.gh_with_routes(), REPO, OWNER, 2))[0], READY)

    def test_task_definition_read_from_main_only(self):
        gh = self.gh_with_routes()
        fetch_facts(gh, REPO, OWNER, 2)
        self.assertIn(f"/repos/{REPO}/contents/tasks/T-001.json?ref=main", gh.routes)

    def test_main_ready_exit_zero(self):
        self.assertEqual(main(self.env(), gh=self.gh_with_routes()), 0)

    def test_any_api_error_fails_closed(self):
        for path in (f"/repos/{REPO}/actions/runs/555", f"/repos/{REPO}/pulls/2"):
            gh = self.gh_with_routes()
            gh.routes[path] = http_error(500, "Server Error")
            self.assertEqual(main(self.env(), gh=gh), 1, path)

    def test_missing_claim_ref_fails_closed(self):
        gh = self.gh_with_routes()
        gh.refs.clear()
        self.assertEqual(main(self.env(), gh=gh), 1)

    def test_guards(self):
        for e in (self.env(GITHUB_ACTOR="someone"), self.env(GITHUB_EVENT_NAME="push"),
                  self.env(GITHUB_REF="refs/heads/pilot/T-001"), self.env(PR_NUMBER="2; rm -rf /"), {}):
            self.assertEqual(main(e, gh=self.gh_with_routes()), 2)


if __name__ == "__main__":
    unittest.main()
