"""Fail-closed pilot status: claim and CI provenance, complete collections, verdicts, PR consistency."""
import base64
import copy
import json
import unittest

from lockcheck.pilot_status import (BLOCKED, NEEDS_REVIEW, NEEDS_REVISION, READY, WAITING, classify_verdicts,
                                    evaluate, fetch_facts, main)
from tests.fake_github import FakeGitHub, Page, http_error

REPO, OWNER = "example-owner/example-repo", "example-owner"
HEAD, OLD, MAIN_SHA, TAG_SHA = "a" * 40, "b" * 40, "c" * 40, "e" * 40
TESTS_BLOB = "9" * 40
TASK = {"task_id": "T-001", "agent": "claude", "branch": "pilot/T-001",
        "allowed_paths": ["pilot/__init__.py", "pilot/temperature.py", "tests/test_temperature.py"],
        "max_revision_rounds": 2}
META = {"task_id": "T-001", "agent": "claude", "repo": REPO, "actor": OWNER, "triggering_actor": OWNER,
        "workflow": ".github/workflows/claim-task.yml", "ref": "refs/heads/main", "sha": MAIN_SHA,
        "run_id": "555", "run_attempt": "1"}
CLAIM_RUN = {"id": 555, "repository": {"full_name": REPO}, "path": ".github/workflows/claim-task.yml",
             "event": "workflow_dispatch", "actor": {"login": OWNER}, "triggering_actor": {"login": OWNER},
             "head_branch": "main", "head_sha": MAIN_SHA, "run_attempt": 1, "display_title": "claim-task T-001",
             "status": "completed", "conclusion": "success", "created_at": "2026-11-21T09:00:00Z",
             "updated_at": "2026-11-21T09:01:00Z"}
CI_RUN = {"id": 700, "path": ".github/workflows/tests.yml", "event": "pull_request", "head_sha": HEAD,
          "head_branch": "pilot/T-001", "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO},
          "pull_requests": [{"number": 2}], "run_attempt": 1, "status": "completed", "conclusion": "success"}
JOB = {"id": 900, "run_id": 700, "run_attempt": 1, "head_sha": HEAD, "name": "unittest", "status": "completed",
       "conclusion": "success", "check_run_url": f"https://api.github.com/repos/{REPO}/check-runs/900"}
CHECK = {"id": 900, "name": "unittest", "head_sha": HEAD, "status": "completed", "conclusion": "success",
         "app": {"slug": "github-actions", "id": 15368}}
RULES = [{"type": "deletion"}, {"type": "non_fast_forward"},
         {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
         {"type": "required_status_checks",
          "parameters": {"required_status_checks": [{"context": "unittest", "integration_id": 15368}]}}]


def verdict(cid, sha, word, login=OWNER, assoc="OWNER", edited=False, task="T-001", first=None):
    created = f"2026-11-21T10:{cid:02d}:00Z"
    line = first if first is not None else f"CODEX-REVIEW {task} {sha} {word}"
    return {"id": cid, "user": {"login": login}, "author_association": assoc, "created_at": created,
            "updated_at": "2026-11-21T11:59:59Z" if edited else created, "body": line + "\n\nFindings: synthetic."}


def facts(**over):
    pr = {"number": 2, "state": "open", "merged": False, "created_at": "2026-11-21T09:30:00Z",
          "changed_files": 2, "comments": 1, "commits": 1,
          "head": {"ref": "pilot/T-001", "sha": HEAD, "repo": {"full_name": REPO}}, "base": {"ref": "main", "sha": MAIN_SHA}}
    f = {"owner": OWNER, "repo": REPO, "task": copy.deepcopy(TASK), "pr": pr, "pr_recheck": copy.deepcopy(pr),
         "rules": copy.deepcopy(RULES),
         "files": [{"filename": "pilot/temperature.py", "status": "added"},
                   {"filename": "tests/test_temperature.py", "status": "added"}],
         "comments": [verdict(1, HEAD, "APPROVED")], "checks": [copy.deepcopy(CHECK)],
         "tests_yml_main": TESTS_BLOB, "tests_yml_head": TESTS_BLOB,
         "ci_runs": [copy.deepcopy(CI_RUN)], "ci_jobs": [copy.deepcopy(JOB)], "ci_jobs_for": (700, 1),
         "claim_ref": {"ref": "refs/lockcheck/task-T-001", "object": {"type": "tag", "sha": TAG_SHA}},
         "claim_tag": {"sha": TAG_SHA, "tag": "claim-T-001", "message": json.dumps(META) + "\n",
                       "object": {"type": "commit", "sha": MAIN_SHA}},
         "claim_run": copy.deepcopy(CLAIM_RUN)}
    f.update(over)
    return f


def v(f):
    return evaluate(f)[0]


def with_meta(**changes):
    f = facts()
    f["claim_tag"]["message"] = json.dumps(dict(META, **changes))
    return f


class TestReady(unittest.TestCase):
    def test_all_conditions_met(self):
        verdict_, reasons, details = evaluate(facts())
        self.assertEqual(verdict_, READY, reasons)


class TestFinding1ClaimProvenance(unittest.TestCase):
    def test_ref_and_tag_object(self):
        self.assertEqual(v(facts(claim_ref=None)), BLOCKED)
        self.assertEqual(v(facts(claim_ref={"ref": "refs/lockcheck/task-T-001", "object": {"type": "commit", "sha": MAIN_SHA}})), BLOCKED)
        f = facts(); f["claim_tag"]["sha"] = "f" * 40
        self.assertEqual(v(f), BLOCKED)                                        # tag object != ref target
        f = facts(); f["claim_tag"]["tag"] = "claim-T-002"
        self.assertEqual(v(f), BLOCKED)
        f = facts(); f["claim_tag"]["message"] = "not json"
        self.assertEqual(v(f), BLOCKED)

    def test_tag_target_must_equal_recorded_sha(self):
        f = facts(); f["claim_tag"]["object"]["sha"] = OLD
        self.assertEqual(v(f), BLOCKED)
        f = facts(); f["claim_tag"]["object"]["type"] = "tree"
        self.assertEqual(v(f), BLOCKED)

    def test_run_head_sha_must_equal_recorded_sha(self):
        f = facts(); f["claim_run"]["head_sha"] = OLD
        self.assertEqual(v(f), BLOCKED)
        self.assertEqual(v(with_meta(sha=OLD)), BLOCKED)

    def test_attempt_one_only(self):
        f = facts(); f["claim_run"]["run_attempt"] = 2
        self.assertEqual(v(f), BLOCKED)
        self.assertEqual(v(with_meta(run_attempt="2")), BLOCKED)

    def test_run_must_be_linked_to_this_task(self):
        for title in ("claim-task T-002", "claim-task", "", None):
            f = facts(); f["claim_run"]["display_title"] = title
            self.assertEqual(v(f), BLOCKED, title)

    def test_run_identity_fields(self):
        for key, bad in (("id", 556), ("repository", {"full_name": "x/y"}), ("path", ".github/workflows/x.yml"),
                         ("event", "push"), ("actor", {"login": "x"}), ("triggering_actor", {"login": "x"}),
                         ("head_branch", "pilot/T-001"), ("status", "in_progress"), ("conclusion", "failure")):
            f = facts(); f["claim_run"][key] = bad
            self.assertEqual(v(f), BLOCKED, key)
        for key, bad in (("task_id", "T-002"), ("agent", "codex"), ("repo", "x/y"), ("actor", "x"),
                         ("triggering_actor", "x"), ("workflow", ".github/workflows/x.yml"), ("ref", "refs/heads/x"),
                         ("run_id", "abc")):
            self.assertEqual(v(with_meta(**{key: bad})), BLOCKED, key)

    def test_claim_must_be_finished_before_pr_opened(self):
        f = facts(); f["claim_run"]["updated_at"] = "2026-11-21T09:45:00Z"
        self.assertEqual(v(f), BLOCKED)
        f = facts(); f["claim_run"]["updated_at"] = None
        self.assertEqual(v(f), BLOCKED)

    def test_rest_style_run_path_accepted(self):
        f = facts(); f["claim_run"]["path"] = f"{REPO}/.github/workflows/claim-task.yml@refs/heads/main"
        self.assertEqual(v(f), READY)


class TestFinding2CIProvenance(unittest.TestCase):
    def test_tests_workflow_must_be_unchanged(self):
        self.assertEqual(v(facts(tests_yml_head="8" * 40)), BLOCKED)
        self.assertEqual(v(facts(tests_yml_main=None)), BLOCKED)

    def test_wrong_workflow_or_event_is_not_trusted(self):
        for key, bad in (("path", ".github/workflows/evil.yml"), ("event", "push"), ("head_sha", OLD),
                         ("head_branch", "pilot/T-002"), ("repository", {"full_name": "x/y"}),
                         ("head_repository", {"full_name": "fork/y"})):
            f = facts(); f["ci_runs"][0][key] = bad
            self.assertEqual(v(f), WAITING, key)                              # no trusted run -> not ready

    def test_run_must_be_associated_with_this_pr(self):
        f = facts(); f["ci_runs"][0]["pull_requests"] = [{"number": 3}]
        self.assertEqual(v(f), BLOCKED)

    def test_wrong_attempt_jobs_rejected(self):
        self.assertEqual(v(facts(ci_jobs_for=(700, 2))), BLOCKED)
        f = facts(); f["ci_jobs"][0]["run_attempt"] = 2
        self.assertEqual(v(f), BLOCKED)
        f = facts(); f["ci_runs"][0]["run_attempt"] = 2
        self.assertEqual(v(f), BLOCKED)                                       # jobs fetched for attempt 1

    def test_job_identity(self):
        for key, bad in (("run_id", 701), ("head_sha", OLD)):
            f = facts(); f["ci_jobs"][0][key] = bad
            self.assertEqual(v(f), BLOCKED, key)
        self.assertEqual(v(facts(ci_jobs=[])), BLOCKED)
        self.assertEqual(v(facts(ci_jobs=[copy.deepcopy(JOB), dict(JOB, id=901)])), BLOCKED)

    def test_check_name_and_app_alone_are_not_trusted(self):
        f = facts(); f["checks"][0]["id"] = 999                              # same name/app, not the job's check
        self.assertEqual(v(f), BLOCKED)
        for key, bad in (("app", {"slug": "github-actions", "id": 1}), ("app", {"slug": "other", "id": 15368}),
                         ("head_sha", OLD), ("name", "unittest2")):
            f = facts(); f["checks"][0][key] = bad
            self.assertEqual(v(f), BLOCKED, key)
        f = facts(); f["ci_jobs"][0]["check_run_url"] = f"https://api.github.com/repos/{REPO}/check-runs/1"
        self.assertEqual(v(f), BLOCKED)

    def test_outcomes(self):
        f = facts(); f["ci_jobs"][0]["conclusion"] = "failure"; f["ci_runs"][0]["conclusion"] = "failure"
        self.assertEqual(v(f), NEEDS_REVISION)
        f = facts(); f["ci_runs"][0]["status"] = "in_progress"
        self.assertEqual(v(f), WAITING)
        self.assertEqual(v(facts(ci_runs=[])), WAITING)

    def test_newest_run_is_used(self):
        older = dict(CI_RUN, id=650)
        newer_failed = dict(CI_RUN, id=700, conclusion="failure")
        job = dict(JOB, conclusion="failure")
        self.assertEqual(v(facts(ci_runs=[older, newer_failed], ci_jobs=[job])), NEEDS_REVISION)


class TestFinding3Completeness(unittest.TestCase):
    def test_file_count_must_match_pr(self):
        f = facts(); f["pr"]["changed_files"] = 3; f["pr_recheck"]["changed_files"] = 3
        self.assertEqual(v(f), BLOCKED)

    def test_comment_count_must_match_pr(self):
        f = facts(); f["pr"]["comments"] = 2; f["pr_recheck"]["comments"] = 2
        self.assertEqual(v(f), BLOCKED)

    def test_rename_source_and_destination_checked(self):
        renamed_in = {"filename": "pilot/temperature.py", "status": "renamed", "previous_filename": "lockcheck/lock.py"}
        f = facts(files=[renamed_in, {"filename": "tests/test_temperature.py", "status": "added"}])
        self.assertEqual(v(f), BLOCKED)
        no_source = {"filename": "pilot/temperature.py", "status": "renamed"}
        self.assertEqual(v(facts(files=[no_source, {"filename": "tests/test_temperature.py", "status": "added"}])), BLOCKED)
        ok = {"filename": "pilot/temperature.py", "status": "renamed", "previous_filename": "pilot/__init__.py"}
        self.assertEqual(v(facts(files=[ok, {"filename": "tests/test_temperature.py", "status": "added"}])), READY)

    def test_unsupported_status_and_paths(self):
        copied = {"filename": "pilot/temperature.py", "status": "copied", "previous_filename": "pilot/__init__.py"}
        self.assertEqual(v(facts(files=[copied, {"filename": "tests/test_temperature.py", "status": "added"}])), BLOCKED)
        for extra in (".github/workflows/tests.yml", "lockcheck/lock.py", "tasks/T-001.json"):
            f = facts(files=[{"filename": "pilot/temperature.py", "status": "added"}, {"filename": extra, "status": "modified"}])
            self.assertEqual(v(f), BLOCKED, extra)
        self.assertEqual(v(facts(files=[])), BLOCKED)


class TestFinding4Verdicts(unittest.TestCase):
    def test_invalid_newer_owner_verdict_never_restores_older_approval(self):
        invalid = [verdict(2, HEAD, "APPROVED", edited=True), verdict(2, HEAD, "", first=f"CODEX-REVIEW T-001 {HEAD}  APPROVED"),
                   verdict(2, HEAD, "", first=f"CODEX-REVIEW T-001 {HEAD} APPROVED\r"), verdict(2, HEAD, "", first="CODEX-REVIEW looks good"),
                   verdict(2, HEAD, "APPROVED", task="T-002"), verdict(2, HEAD, "", first=f"CODEX-REVIEW T-001 {HEAD} approved")]
        for bad in invalid:
            f = facts(comments=[verdict(1, HEAD, "APPROVED"), bad]); f["pr"]["comments"] = f["pr_recheck"]["comments"] = 2
            self.assertEqual(v(f), NEEDS_REVIEW, bad["body"][:70])

    def test_non_owner_comments_are_ignored(self):
        f = facts(comments=[verdict(1, HEAD, "CHANGES_REQUESTED"), verdict(2, HEAD, "APPROVED", login="x", assoc="NONE")])
        f["pr"]["comments"] = f["pr_recheck"]["comments"] = 2
        self.assertEqual(v(f), NEEDS_REVISION)

    def test_exact_first_line_required(self):
        lead = dict(verdict(1, HEAD, "APPROVED"), body=" " + verdict(1, HEAD, "APPROVED")["body"])
        self.assertEqual(v(facts(comments=[lead])), NEEDS_REVIEW)            # leading space: not a verdict line
        late = dict(verdict(1, HEAD, "APPROVED"), body="LGTM\n" + verdict(1, HEAD, "APPROVED")["body"])
        self.assertEqual(v(facts(comments=[late])), NEEDS_REVIEW)

    def test_stale_and_rounds(self):
        self.assertEqual(v(facts(comments=[verdict(1, OLD, "APPROVED")])), NEEDS_REVIEW)
        shas = ["1" * 40, "2" * 40, "3" * 40]
        three = [verdict(i + 1, s, "CHANGES_REQUESTED") for i, s in enumerate(shas)] + [verdict(9, HEAD, "APPROVED")]
        f = facts(comments=three); f["pr"]["comments"] = f["pr_recheck"]["comments"] = 4
        self.assertEqual(v(f), BLOCKED)

    def test_classification_orders_by_id(self):
        out = classify_verdicts([verdict(3, HEAD, "APPROVED"), verdict(1, OLD, "CHANGES_REQUESTED")], OWNER, "T-001")
        self.assertEqual([x["id"] for x in out], [1, 3])


class TestFinding5PRConsistency(unittest.TestCase):
    def test_recheck_must_match(self):
        for path, value in ((("head", "sha"), OLD), (("base", "sha"), OLD), (("state",), "closed"),
                            (("comments",), 2), (("changed_files",), 3), (("commits",), 2), (("merged",), True)):
            f = facts()
            target = f["pr_recheck"]
            for k in path[:-1]:
                target = target[k]
            target[path[-1]] = value
            self.assertEqual(v(f), BLOCKED, path)
        self.assertEqual(v(facts(pr_recheck=None)), BLOCKED)

    def test_merged_must_be_explicitly_false(self):
        f = facts(); f["pr"]["merged"] = None; f["pr_recheck"]["merged"] = None
        self.assertEqual(v(f), BLOCKED)


class TestFinding7Ruleset(unittest.TestCase):
    def test_ruleset_requirements(self):
        self.assertEqual(v(facts(rules=None)), BLOCKED)
        for drop in ("deletion", "non_fast_forward", "pull_request", "required_status_checks"):
            self.assertEqual(v(facts(rules=[r for r in RULES if r["type"] != drop])), BLOCKED, drop)
        wrong_source = copy.deepcopy(RULES)
        wrong_source[3]["parameters"]["required_status_checks"] = [{"context": "unittest"}]   # any source
        self.assertEqual(v(facts(rules=wrong_source)), BLOCKED)


# ---- fetch + main against a realistic API double ---------------------------------------------

def gh_for(f=None):
    f = f or facts()
    gh = FakeGitHub(repo=REPO)
    gh.tags[TAG_SHA] = f["claim_tag"]
    gh.refs["refs/lockcheck/task-T-001"] = TAG_SHA
    content = base64.b64encode(json.dumps(TASK).encode()).decode()
    gh.routes.update({
        f"/repos/{REPO}/pulls/2": f["pr"],
        f"/repos/{REPO}/contents/tasks/T-001.json?ref=main": {"type": "file", "content": content},
        f"/repos/{REPO}/rules/branches/main": RULES,
        f"/repos/{REPO}/pulls/2/files?per_page=100": Page(f["files"]),
        f"/repos/{REPO}/issues/2/comments?per_page=100": Page(f["comments"]),
        f"/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100": Page({"total_count": 1, "check_runs": f["checks"]}),
        f"/repos/{REPO}/contents/.github/workflows/tests.yml?ref=main": {"type": "file", "sha": TESTS_BLOB},
        f"/repos/{REPO}/contents/.github/workflows/tests.yml?ref={HEAD}": {"type": "file", "sha": TESTS_BLOB},
        f"/repos/{REPO}/actions/workflows/tests.yml/runs?event=pull_request&head_sha={HEAD}&per_page=100":
            Page({"total_count": 1, "workflow_runs": f["ci_runs"]}),
        f"/repos/{REPO}/actions/runs/700/attempts/1/jobs?per_page=100": Page({"total_count": 1, "jobs": f["ci_jobs"]}),
        f"/repos/{REPO}/actions/runs/555": f["claim_run"]})
    return gh


def env(**over):
    e = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
         "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_OWNER": OWNER, "GITHUB_ACTOR": OWNER,
         "GITHUB_TRIGGERING_ACTOR": OWNER, "PR_NUMBER": "2"}
    e.update(over)
    return e


class TestFetchAndMain(unittest.TestCase):
    def test_end_to_end_ready(self):
        self.assertEqual(evaluate(fetch_facts(gh_for(), REPO, OWNER, 2))[0], READY)
        self.assertEqual(main(env(), gh=gh_for()), 0)

    def test_truncated_pages_fail_closed(self):
        gh = gh_for()
        gh.routes[f"/repos/{REPO}/pulls/2/files?per_page=100"] = Page(facts()["files"], next_path="/repos/x/missing")
        self.assertEqual(main(env(), gh=gh), 1)
        gh = gh_for()
        gh.routes[f"/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100"] = Page({"total_count": 5, "check_runs": [CHECK]})
        self.assertEqual(main(env(), gh=gh), 1)

    def test_pr_changes_during_collection(self):
        gh = gh_for()
        moved = copy.deepcopy(facts()["pr"]); moved["head"]["sha"] = OLD
        real = gh.request
        calls = {"pr": 0}

        def request(method, path, body=None):
            if path == f"/repos/{REPO}/pulls/2":
                calls["pr"] += 1
                if calls["pr"] > 1:
                    return moved, {}
            return real(method, path, body)
        gh.request = request
        verdict_, reasons, _ = evaluate(fetch_facts(gh, REPO, OWNER, 2))
        self.assertEqual(verdict_, BLOCKED)
        self.assertIn("changed while facts were collected", reasons[0])

    def test_any_api_error_fails_closed(self):
        for path in (f"/repos/{REPO}/actions/runs/555", f"/repos/{REPO}/rules/branches/main",
                     f"/repos/{REPO}/contents/.github/workflows/tests.yml?ref={HEAD}"):
            gh = gh_for()
            gh.routes[path] = http_error(500, "Server Error")
            self.assertEqual(main(env(), gh=gh), 1, path)

    def test_task_definition_read_from_main(self):
        gh = gh_for()
        fetch_facts(gh, REPO, OWNER, 2)
        self.assertIn(("GET", f"/repos/{REPO}/contents/tasks/T-001.json?ref=main", None), gh.requests)

    def test_guards(self):
        for e in (env(GITHUB_ACTOR="x"), env(GITHUB_TRIGGERING_ACTOR="x"), env(GITHUB_EVENT_NAME="push"),
                  env(GITHUB_REF="refs/heads/pilot/T-001"), env(PR_NUMBER="2; rm -rf /"), {}):
            self.assertEqual(main(e, gh=gh_for()), 2)


if __name__ == "__main__":
    unittest.main()
