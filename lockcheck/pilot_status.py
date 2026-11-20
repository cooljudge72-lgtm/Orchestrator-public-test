"""Read-only, fail-closed status of a pilot task PR. Runs only in the manual pilot-status workflow.

Verdicts:
  READY_FOR_OWNER  every check passed for the PR's current head commit (nothing merges here)
  NEEDS_REVIEW     no valid owner verdict for the current head commit (none, stale, or the newest is invalid)
  NEEDS_REVISION   the newest valid verdict on the head is CHANGES_REQUESTED, or the trusted tests failed
  WAITING          the trusted unittest job for the head commit has not finished
  BLOCKED          any integrity condition failed, any data is missing or incomplete, or an error occurred

Provenance rules (see docs/PILOT.md for the reasoning and the limits):
  * Claim: refs/lockcheck/task-<id> -> annotated tag (name claim-<id>) -> the commit recorded in the
    tag's identity; that identity names run R; the Actions API shows R is the owner's manual
    claim-task run on main, attempt 1, head SHA == recorded SHA, run title "claim-task <id>",
    concluded success (the run exits 0 only if it acquired the claim) and finished before the PR
    was opened.
  * CI: the newest tests.yml pull_request run for the head commit, on the PR branch, in this repo;
    its current attempt's single "unittest" job succeeded on the head commit; the check run with
    that job's id is from GitHub Actions; tests.yml is identical on main and on the head commit.
  * Collections (files, comments, check runs, workflow runs, jobs) must be complete: counts must
    match the PR / total_count and pagination must end.
  * The PR is fetched again at the end; any change (head, base, state, counts) is BLOCKED.
"""
import base64
import json
import os
import re
import sys

from .claim import CLAIM_WORKFLOW, claim_ref, tag_name, workflow_path
from .github_api import IncompleteError, paginate

READY, NEEDS_REVIEW, NEEDS_REVISION, WAITING, BLOCKED = (
    "READY_FOR_OWNER", "NEEDS_REVIEW", "NEEDS_REVISION", "WAITING", "BLOCKED")
SHA = re.compile(r"[0-9a-f]{40}")
BRANCH = re.compile(r"pilot/(T-\d{3})")
VERDICT_LINE = re.compile(r"CODEX-REVIEW (T-\d{3}) ([0-9a-f]{40}) (APPROVED|CHANGES_REQUESTED)")
TESTS_WORKFLOW, TESTS_JOB, TESTS_APP, ACTIONS_APP_ID = ".github/workflows/tests.yml", "unittest", "github-actions", 15368
FILE_STATUSES = {"added", "modified", "removed", "renamed", "changed"}
PR_SNAPSHOT_KEYS = (("head", "sha"), ("head", "ref"), ("base", "sha"), ("base", "ref"), ("state",), ("merged",),
                    ("changed_files",), ("comments",), ("commits",))


def _get(d, *keys):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _blocked(reason, details=None):
    return BLOCKED, [reason], details or {}


def _norm_path(path, repo):
    return workflow_path(path, repo) or (path or "").split("@", 1)[0]


# ---- verdicts --------------------------------------------------------------------------------

def classify_verdicts(comments, owner, task_id):
    """Owner comments whose first line starts with CODEX-REVIEW, oldest first, each marked valid or
    invalid. Non-owner comments are ignored entirely."""
    out = []
    for c in comments:
        if _get(c, "user", "login") != owner or c.get("author_association") != "OWNER":
            continue
        body = c.get("body") or ""
        first = body.split("\n", 1)[0]
        if not first.startswith("CODEX-REVIEW"):
            continue
        m = VERDICT_LINE.fullmatch(first)          # exact literal line: no extra spaces, no \r
        problem = ""
        if not m:
            problem = "first line is not an exact verdict"
        elif m.group(1) != task_id:
            problem = "verdict names another task"
        elif c.get("updated_at") != c.get("created_at"):
            problem = "verdict comment was edited"
        out.append({"id": c.get("id"), "sha": m.group(2) if m else None, "verdict": m.group(3) if m else None,
                    "valid": not problem, "problem": problem})
    return sorted(out, key=lambda v: (v["id"] is None, v["id"]))


# ---- claim provenance --------------------------------------------------------------------------

def check_claim(f, owner, repo, task, pr_created_at):
    ref, tag, run = f.get("claim_ref"), f.get("claim_tag"), f.get("claim_run")
    tid = task["task_id"]
    if not isinstance(ref, dict) or ref.get("ref") != claim_ref(tid):
        return "task claim ref is missing"
    if _get(ref, "object", "type") != "tag" or not SHA.fullmatch(str(_get(ref, "object", "sha") or "")):
        return "task claim does not point at an annotated tag"
    if not isinstance(tag, dict) or tag.get("sha") != _get(ref, "object", "sha"):
        return "claim tag object does not match the claim ref"
    if tag.get("tag") != tag_name(tid):
        return "claim tag has the wrong name"
    try:
        meta = json.loads(tag.get("message") or "")
    except ValueError:
        return "claim tag message is not a valid identity"
    if not isinstance(meta, dict):
        return "claim tag message is not a valid identity"
    expected = {"task_id": tid, "agent": task["agent"], "repo": repo, "actor": owner, "triggering_actor": owner,
                "workflow": CLAIM_WORKFLOW, "ref": "refs/heads/main", "run_attempt": "1"}
    for key, value in expected.items():
        if meta.get(key) != value:
            return f"claim identity mismatch: {key}"
    if not SHA.fullmatch(str(meta.get("sha", ""))) or not str(meta.get("run_id", "")).isdigit():
        return "claim identity has no valid sha or run id"
    if _get(tag, "object", "type") != "commit" or _get(tag, "object", "sha") != meta["sha"]:
        return "claim tag does not target the recorded commit"
    if not isinstance(run, dict):
        return "claim run could not be read from the Actions API"
    run_checks = [
        (str(run.get("id")) == meta["run_id"], "claim run id does not match"),
        ((_get(run, "repository", "full_name") or "").lower() == repo.lower(), "claim run is in another repository"),
        (_norm_path(run.get("path"), repo) == CLAIM_WORKFLOW, "claim run is not the claim-task workflow"),
        (run.get("event") == "workflow_dispatch", "claim run was not a manual dispatch"),
        (_get(run, "actor", "login") == owner and _get(run, "triggering_actor", "login") == owner,
         "claim run was not started by the owner"),
        (run.get("head_branch") == "main", "claim run did not run on main"),
        (run.get("head_sha") == meta["sha"], "claim run head SHA differs from the recorded claim SHA"),
        (run.get("run_attempt") == 1, "claim run is not attempt 1"),
        (run.get("display_title") == f"claim-task {tid}", "claim run title does not name this task"),
        (run.get("status") == "completed" and run.get("conclusion") == "success",
         "claim run did not succeed (it succeeds only when it acquired the claim)"),
        # Upper bound of publication: the claim existed before the run finished. updated_at is
        # used as that bound; if GitHub updates it later, this check fails closed.
        (bool(run.get("updated_at")) and bool(pr_created_at) and run["updated_at"] <= pr_created_at,
         "cannot show the claim existed before the PR was opened"),
    ]
    for ok, reason in run_checks:
        if not ok:
            return reason
    return ""


# ---- CI provenance -----------------------------------------------------------------------------

def check_ci(f, repo, pr):
    """Returns (state, reason): state in {"ok", "waiting", "failed", "blocked"}."""
    head, branch, number = pr["head"]["sha"], pr["head"]["ref"], pr["number"]
    if not f.get("tests_yml_main") or f.get("tests_yml_main") != f.get("tests_yml_head"):
        return "blocked", "tests.yml on the head commit is not identical to tests.yml on main"
    runs = [r for r in f.get("ci_runs") or []
            if _norm_path(r.get("path"), repo) == TESTS_WORKFLOW and r.get("event") == "pull_request"
            and r.get("head_sha") == head and r.get("head_branch") == branch
            and (_get(r, "repository", "full_name") or "").lower() == repo.lower()
            and (_get(r, "head_repository", "full_name") or "").lower() == repo.lower()]
    if not runs:
        return "waiting", "no trusted tests.yml pull_request run for the head commit yet"
    run = max(runs, key=lambda r: r["id"])
    if not any(p.get("number") == number for p in run.get("pull_requests") or []):
        return "blocked", "newest tests run is not associated with this pull request"
    if run.get("status") != "completed":
        return "waiting", "trusted tests run has not finished"
    jobs = f.get("ci_jobs")
    if not isinstance(jobs, list) or f.get("ci_jobs_for") != (run["id"], run.get("run_attempt")):
        return "blocked", "jobs of the trusted tests run (current attempt) are missing"
    named = [j for j in jobs if j.get("name") == TESTS_JOB]
    if len(named) != 1:
        return "blocked", f"expected exactly one '{TESTS_JOB}' job, found {len(named)}"
    job = named[0]
    if job.get("run_id") != run["id"] or job.get("run_attempt") != run.get("run_attempt") or job.get("head_sha") != head:
        return "blocked", "unittest job does not belong to the trusted run attempt for the head commit"
    checks = [c for c in f.get("checks") or [] if str(c.get("id")) == str(job.get("id"))]
    url_id = str(job.get("check_run_url") or "").rsplit("/", 1)[-1]
    if (len(checks) != 1 or url_id != str(job.get("id")) or checks[0].get("name") != TESTS_JOB
            or _get(checks[0], "app", "slug") != TESTS_APP or _get(checks[0], "app", "id") != ACTIONS_APP_ID
            or checks[0].get("head_sha") != head):
        return "blocked", "check run for the unittest job is missing or not from GitHub Actions"
    if job.get("status") != "completed":
        return "waiting", "unittest job has not finished"
    if job.get("conclusion") != "success" or run.get("conclusion") != "success":
        return "failed", f"trusted unittest job concluded {job.get('conclusion')}"
    return "ok", ""


def check_ruleset(rules):
    """Read-only check that main's effective rules still require a PR and the Actions unittest check."""
    if not isinstance(rules, list):
        return "branch rules for main could not be read"
    types = {r.get("type") for r in rules}
    for needed in ("pull_request", "required_status_checks", "non_fast_forward", "deletion"):
        if needed not in types:
            return f"main is missing the '{needed}' rule"
    contexts = [c for r in rules if r.get("type") == "required_status_checks"
                for c in _get(r, "parameters", "required_status_checks") or []]
    if not any(c.get("context") == TESTS_JOB and c.get("integration_id") == ACTIONS_APP_ID for c in contexts):
        return "main does not require the unittest check from GitHub Actions"
    return ""


# ---- evaluation --------------------------------------------------------------------------------

def check_files(files, task, pr):
    if not isinstance(files, list) or not files:
        return "changed-file list is missing or empty"
    if pr.get("changed_files") != len(files):
        return f"changed-file list is incomplete ({len(files)} of {pr.get('changed_files')})"
    allowed = set(task.get("allowed_paths") or [])
    for entry in files:
        if entry.get("status") not in FILE_STATUSES:
            return f"unsupported file status {entry.get('status')!r} for {entry.get('filename')}"
        for path in (entry.get("filename"), entry.get("previous_filename")):
            if path is not None and path not in allowed:
                return f"file outside the task's allowed paths: {path}"
        if entry.get("status") == "renamed" and not entry.get("previous_filename"):
            return f"rename without a source path: {entry.get('filename')}"
    return ""


def evaluate(f):
    """f: facts fetched from the API. Returns (verdict, reasons, details). Pure function."""
    if f.get("error"):
        return _blocked(f["error"])
    owner, repo, pr, task = f.get("owner"), f.get("repo"), f.get("pr"), f.get("task")
    if not owner or not repo or not isinstance(pr, dict):
        return _blocked("incomplete facts")
    bm = BRANCH.fullmatch(_get(pr, "head", "ref") or "")
    if not bm:
        return _blocked("head branch is not pilot/T-xxx")
    task_id = bm.group(1)
    if not isinstance(task, dict) or task.get("task_id") != task_id or task.get("branch") != _get(pr, "head", "ref"):
        return _blocked("no matching task definition on main")
    if pr.get("state") != "open" or pr.get("merged") is not False:
        return _blocked("pull request is not open (or already merged)")
    if _get(pr, "base", "ref") != "main":
        return _blocked("pull request does not target main")
    if (_get(pr, "head", "repo", "full_name") or "").lower() != repo.lower():
        return _blocked("pull request comes from a fork or another repository")
    head = _get(pr, "head", "sha") or ""
    if not SHA.fullmatch(head):
        return _blocked("head SHA is missing")
    details = {"task": task_id, "head": head}
    recheck = f.get("pr_recheck")
    if not isinstance(recheck, dict) or any(_get(pr, *k) != _get(recheck, *k) for k in PR_SNAPSHOT_KEYS):
        return _blocked("the pull request changed while facts were collected; run the status again", details)

    for problem in (check_ruleset(f.get("rules")), check_claim(f, owner, repo, task, pr.get("created_at")),
                    check_files(f.get("files"), task, pr)):
        if problem:
            return _blocked(problem, details)
    comments = f.get("comments")
    if not isinstance(comments, list) or pr.get("comments") != len(comments):
        return _blocked("comment list is incomplete", details)

    verdicts = classify_verdicts(comments, owner, task_id)
    rounds = len({v["sha"] for v in verdicts if v["valid"] and v["verdict"] == "CHANGES_REQUESTED"})
    limit = task.get("max_revision_rounds")
    details.update(revision_rounds=rounds, max_revision_rounds=limit)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        return _blocked("task has no valid max_revision_rounds", details)
    if rounds > limit:
        return _blocked(f"revision rounds exceeded ({rounds}/{limit})", details)

    ci_state, ci_reason = check_ci(f, repo, pr)
    details["ci"] = ci_state
    if ci_state == "blocked":
        return _blocked(ci_reason, details)
    if ci_state == "waiting":
        return WAITING, [ci_reason], details
    if ci_state == "failed":
        return NEEDS_REVISION, [ci_reason], details

    latest = verdicts[-1] if verdicts else None
    details["latest_verdict"] = latest and {k: latest[k] for k in ("id", "sha", "verdict", "valid")}
    if latest is None:
        return NEEDS_REVIEW, ["no owner-posted review verdict yet"], details
    if not latest["valid"]:
        return NEEDS_REVIEW, [f"newest owner verdict is invalid ({latest['problem']}); older verdicts are not used"], details
    if latest["sha"] != head:
        return NEEDS_REVIEW, ["newest verdict is for an older commit (stale; any approval is void)"], details
    if latest["verdict"] == "CHANGES_REQUESTED":
        return NEEDS_REVISION, [f"changes requested on the head commit (round {rounds} of {limit})"], details
    return READY, ["claim provenance, files, trusted CI and owner approval verified for the head commit"], details


# ---- I/O (read-only) --------------------------------------------------------------------------

def _content_sha(gh, repo, path, ref):
    data = gh.call("GET", f"/repos/{repo}/contents/{path}?ref={ref}")
    return data.get("sha") if isinstance(data, dict) and data.get("type") == "file" else None


def fetch_facts(gh, repo, owner, number):
    """Collect every fact for one PR snapshot. Incomplete data raises; callers fail closed."""
    pr = gh.call("GET", f"/repos/{repo}/pulls/{number}")
    facts = {"owner": owner, "repo": repo, "pr": pr}
    bm = BRANCH.fullmatch(_get(pr, "head", "ref") or "")
    head = _get(pr, "head", "sha") or ""
    if not bm or not SHA.fullmatch(head):
        return facts
    task_id = bm.group(1)
    raw = gh.call("GET", f"/repos/{repo}/contents/tasks/{task_id}.json?ref=main")    # trusted copy only
    facts["task"] = json.loads(base64.b64decode(raw["content"]).decode("utf-8"))
    facts["rules"] = gh.call("GET", f"/repos/{repo}/rules/branches/main")
    facts["files"] = paginate(gh, f"/repos/{repo}/pulls/{number}/files")
    facts["comments"] = paginate(gh, f"/repos/{repo}/issues/{number}/comments")
    facts["checks"] = paginate(gh, f"/repos/{repo}/commits/{head}/check-runs", key="check_runs")
    facts["tests_yml_main"] = _content_sha(gh, repo, TESTS_WORKFLOW, "main")
    facts["tests_yml_head"] = _content_sha(gh, repo, TESTS_WORKFLOW, head)
    facts["ci_runs"] = paginate(gh, f"/repos/{repo}/actions/workflows/tests.yml/runs?event=pull_request&head_sha={head}",
                                key="workflow_runs")
    trusted = [r for r in facts["ci_runs"] if _norm_path(r.get("path"), repo) == TESTS_WORKFLOW]
    if trusted:
        run = max(trusted, key=lambda r: r["id"])
        facts["ci_jobs"] = paginate(gh, f"/repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs",
                                    key="jobs")
        facts["ci_jobs_for"] = (run["id"], run["run_attempt"])
    facts["claim_ref"] = gh.call("GET", f"/repos/{repo}/git/ref/{claim_ref(task_id)[len('refs/'):]}")
    tag_sha = _get(facts["claim_ref"], "object", "sha")
    if _get(facts["claim_ref"], "object", "type") == "tag" and SHA.fullmatch(str(tag_sha or "")):
        facts["claim_tag"] = gh.call("GET", f"/repos/{repo}/git/tags/{tag_sha}")
        try:
            run_id = str(json.loads(facts["claim_tag"].get("message") or "").get("run_id", ""))
        except (ValueError, AttributeError):
            run_id = ""
        if run_id.isdigit():
            facts["claim_run"] = gh.call("GET", f"/repos/{repo}/actions/runs/{run_id}")
    facts["pr_recheck"] = gh.call("GET", f"/repos/{repo}/pulls/{number}")             # snapshot consistency
    return facts


def render(verdict, reasons, details):
    lines = [f"## Pilot status: `{verdict}`", ""] + [f"- {r}" for r in reasons] + ["", "| Detail | Value |", "|---|---|"]
    lines += [f"| {k} | `{v}` |" for k, v in details.items()]
    lines += ["", "Nothing is merged automatically. Merge only with the SHA check in docs/PILOT.md."]
    return "\n".join(lines) + "\n"


def main(env=os.environ, gh=None):
    owner = env.get("GITHUB_REPOSITORY_OWNER", "")
    guards = [(env.get("GITHUB_ACTIONS") == "true", "not running in GitHub Actions"),
              (env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "not a manual run"),
              (env.get("GITHUB_REF") == "refs/heads/main", "not running on main"),
              (bool(owner) and env.get("GITHUB_ACTOR") == owner, "actor is not the repository owner"),
              (env.get("GITHUB_TRIGGERING_ACTOR") == owner, "triggering actor is not the repository owner"),
              (str(env.get("PR_NUMBER", "")).isdigit(), "PR number is not numeric")]
    for ok, reason in guards:
        if not ok:
            print(f"STATUS REFUSED: {reason}")
            return 2
    try:
        if gh is None:
            from .github_api import GitHub
            gh = GitHub(env["GITHUB_TOKEN"])
        verdict, reasons, details = evaluate(fetch_facts(gh, env["GITHUB_REPOSITORY"], owner, int(env["PR_NUMBER"])))
    except IncompleteError as err:
        verdict, reasons, details = BLOCKED, [f"incomplete API data: {err}"], {}
    except Exception as err:                         # noqa: BLE001 - fail closed on any error
        verdict, reasons, details = BLOCKED, [f"error while reading facts: {type(err).__name__}"], {}
    report = render(verdict, reasons, details)
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report)
    return 0 if verdict == READY else 1


if __name__ == "__main__":
    sys.exit(main())
