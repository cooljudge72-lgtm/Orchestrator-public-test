"""Read-only, fail-closed status of a pilot task PR. Runs only in the manual pilot-status workflow.

Verdicts:
  READY_FOR_OWNER  every check below passed; the owner may decide to merge (nothing merges here)
  NEEDS_REVIEW     no valid review verdict for the CURRENT head commit (none yet, or stale)
  NEEDS_REVISION   the latest verdict on the head commit is CHANGES_REQUESTED, or tests failed
  WAITING          the required unittest check on the head commit has not finished
  BLOCKED          any integrity/security condition failed, data is missing, or an error occurred

Review verdicts are PR comments written by the repository owner whose first line is exactly
    CODEX-REVIEW <TASK_ID> <40-hex head SHA> APPROVED|CHANGES_REQUESTED
and that were never edited. Only the latest such comment counts, and only if its SHA equals the
PR's current head: any new commit therefore invalidates an earlier approval automatically.
"""
import base64
import json
import os
import re
import sys

from .claim import CLAIM_WORKFLOW, TASK_ID, claim_ref, workflow_path

READY, NEEDS_REVIEW, NEEDS_REVISION, WAITING, BLOCKED = (
    "READY_FOR_OWNER", "NEEDS_REVIEW", "NEEDS_REVISION", "WAITING", "BLOCKED")
MARKER = re.compile(r"CODEX-REVIEW (T-\d{3}) ([0-9a-f]{40}) (APPROVED|CHANGES_REQUESTED)")
BRANCH = re.compile(r"pilot/(T-\d{3})")
TESTS_CHECK, TESTS_APP = "unittest", "github-actions"


def _blocked(reason, details=None):
    return BLOCKED, [reason], details or {}


def parse_verdicts(comments, owner, task_id):
    """Owner-authored, unedited, exactly formatted verdicts for this task, oldest first."""
    verdicts = []
    for c in comments:
        user = c.get("user") or {}
        if user.get("login") != owner or c.get("author_association") != "OWNER":
            continue
        if c.get("updated_at") != c.get("created_at"):
            continue
        lines = [ln.strip() for ln in (c.get("body") or "").splitlines() if ln.strip()]
        m = MARKER.fullmatch(lines[0]) if lines else None
        if not m or m.group(1) != task_id:
            continue
        verdicts.append({"id": c["id"], "created_at": c["created_at"], "sha": m.group(2), "verdict": m.group(3)})
    return sorted(verdicts, key=lambda v: (v["created_at"], v["id"]))


def check_claim(claim, run, owner, repo, task, pr_created_at):
    """'' if the claim was provably taken by the owner's claim-task run on main, else the reason."""
    if not isinstance(claim, dict) or claim.get("type") != "tag" or not isinstance(claim.get("meta"), dict):
        return "task claim is missing or carries no identity"
    m = claim["meta"]
    expected = {"task_id": task["task_id"], "agent": task["agent"], "repo": repo, "actor": owner,
                "triggering_actor": owner, "workflow": CLAIM_WORKFLOW, "ref": "refs/heads/main"}
    for key, value in expected.items():
        if m.get(key) != value:
            return f"claim identity mismatch: {key}"
    if not str(m.get("run_id", "")).isdigit() or not str(m.get("run_attempt", "")).isdigit():
        return "claim run id/attempt is not numeric"
    if not isinstance(run, dict):
        return "claim run could not be read from the Actions API"
    r_actor = (run.get("actor") or {}).get("login")
    r_trigger = (run.get("triggering_actor") or {}).get("login")
    run_checks = [
        (str(run.get("id")) == str(m["run_id"]), "claim run id does not match"),
        (((run.get("repository") or {}).get("full_name") or "").lower() == repo.lower(), "claim run is in another repository"),
        ((workflow_path(run.get("path"), repo) or (run.get("path") or "").split("@", 1)[0]) == CLAIM_WORKFLOW,
         "claim run is not the claim-task workflow"),
        (run.get("event") == "workflow_dispatch", "claim run was not a manual dispatch"),
        (r_actor == owner and r_trigger == owner, "claim run was not started by the owner"),
        (run.get("head_branch") == "main", "claim run did not run on main"),
        (str(run.get("run_attempt")) == str(m["run_attempt"]), "claim run was re-run; identity no longer matches"),
        (run.get("status") == "completed" and run.get("conclusion") == "success", "claim run did not succeed"),
        (bool(run.get("created_at")) and bool(pr_created_at) and run["created_at"] <= pr_created_at,
         "the PR was opened before the task was claimed"),
    ]
    for ok, reason in run_checks:
        if not ok:
            return reason
    return ""


def evaluate(f):
    """f: facts fetched from the API. Returns (verdict, reasons, details). Pure function."""
    owner, repo, pr, task = f.get("owner"), f.get("repo"), f.get("pr"), f.get("task")
    if not owner or not repo or not isinstance(pr, dict):
        return _blocked("incomplete facts")
    branch = (pr.get("head") or {}).get("ref") or ""
    bm = BRANCH.fullmatch(branch)
    if not bm:
        return _blocked("head branch is not pilot/T-xxx")
    task_id = bm.group(1)
    if not isinstance(task, dict) or task.get("task_id") != task_id or task.get("branch") != branch:
        return _blocked("no matching task definition on main")
    if pr.get("state") != "open" or pr.get("merged"):
        return _blocked("pull request is not open (or already merged)")
    if (pr.get("base") or {}).get("ref") != "main":
        return _blocked("pull request does not target main")
    if (((pr.get("head") or {}).get("repo") or {}).get("full_name") or "").lower() != repo.lower():
        return _blocked("pull request comes from a fork or another repository")
    head = (pr.get("head") or {}).get("sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return _blocked("head SHA is missing")
    details = {"task": task_id, "head": head}

    problem = check_claim(f.get("claim"), f.get("claim_run"), owner, repo, task, pr.get("created_at"))
    if problem:
        return _blocked(problem, details)

    files = f.get("files")
    allowed = set(task.get("allowed_paths") or [])
    if not isinstance(files, list) or not files:
        return _blocked("changed-file list is missing or empty", details)
    outside = sorted(set(files) - allowed)
    if outside:
        return _blocked("files outside the task's allowed paths: " + ", ".join(outside[:5]), details)

    runs = [c for c in f.get("checks") or [] if c.get("name") == TESTS_CHECK
            and c.get("app") == TESTS_APP and c.get("head_sha") == head]
    latest_check = max(runs, key=lambda c: c["id"]) if runs else None
    details["unittest"] = latest_check and (latest_check.get("status"), latest_check.get("conclusion"))

    verdicts = parse_verdicts(f.get("comments") or [], owner, task_id)
    rounds = len({v["sha"] for v in verdicts if v["verdict"] == "CHANGES_REQUESTED"})
    limit = task.get("max_revision_rounds")
    details.update(revision_rounds=rounds, max_revision_rounds=limit)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        return _blocked("task has no valid max_revision_rounds", details)
    if rounds > limit:
        return _blocked(f"revision rounds exceeded ({rounds}/{limit})", details)

    if latest_check is None or latest_check.get("status") != "completed":
        return WAITING, ["required unittest check on the head commit has not finished"], details
    if latest_check.get("conclusion") != "success":
        return NEEDS_REVISION, [f"unittest on the head commit is {latest_check.get('conclusion')}"], details

    latest = verdicts[-1] if verdicts else None
    details["latest_verdict"] = latest
    if latest is None:
        return NEEDS_REVIEW, ["no owner-posted review verdict yet"], details
    if latest["sha"] != head:
        return NEEDS_REVIEW, ["latest verdict is for an older commit (stale; any approval is void)"], details
    if latest["verdict"] == "CHANGES_REQUESTED":
        return NEEDS_REVISION, [f"changes requested on the head commit (round {rounds} of {limit})"], details
    return READY, ["claim verified; allowed files only; unittest passed; approved on the head commit"], details


# ---- I/O (read-only) --------------------------------------------------------------------------

def _all(gh, path, pages=5):
    items = []
    for page in range(1, pages + 1):
        sep = "&" if "?" in path else "?"
        batch = gh.call("GET", f"{path}{sep}per_page=100&page={page}") or []
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def fetch_facts(gh, repo, owner, number):
    pr = gh.call("GET", f"/repos/{repo}/pulls/{number}")
    facts = {"owner": owner, "repo": repo, "pr": pr}
    bm = BRANCH.fullmatch((pr.get("head") or {}).get("ref") or "")
    if not bm:
        return facts
    task_id = bm.group(1)
    raw = gh.call("GET", f"/repos/{repo}/contents/tasks/{task_id}.json?ref=main")   # trusted copy only
    facts["task"] = json.loads(base64.b64decode(raw["content"]).decode("utf-8"))
    facts["files"] = [x["filename"] for x in _all(gh, f"/repos/{repo}/pulls/{number}/files")]
    head = pr["head"]["sha"]
    checks = gh.call("GET", f"/repos/{repo}/commits/{head}/check-runs?per_page=100") or {}
    facts["checks"] = [{"id": c["id"], "name": c["name"], "status": c["status"], "conclusion": c["conclusion"],
                        "head_sha": c["head_sha"], "app": (c.get("app") or {}).get("slug")}
                       for c in checks.get("check_runs", [])]
    facts["comments"] = _all(gh, f"/repos/{repo}/issues/{number}/comments")
    ref = gh.call("GET", f"/repos/{repo}/git/ref/{claim_ref(task_id)[len('refs/'):]}")
    obj = (ref or {}).get("object") or {}
    claim = {"type": obj.get("type")}
    if obj.get("type") == "tag":
        claim["meta"] = json.loads(gh.call("GET", f"/repos/{repo}/git/tags/{obj['sha']}")["message"])
        run_id = str(claim["meta"].get("run_id", ""))
        if run_id.isdigit():
            facts["claim_run"] = gh.call("GET", f"/repos/{repo}/actions/runs/{run_id}")
    facts["claim"] = claim
    return facts


def render(verdict, reasons, details):
    lines = [f"## Pilot status: `{verdict}`", ""] + [f"- {r}" for r in reasons] + ["", "| Detail | Value |", "|---|---|"]
    lines += [f"| {k} | `{v}` |" for k, v in details.items()]
    lines += ["", "Nothing is merged automatically. Merging is the owner's decision."]
    return "\n".join(lines) + "\n"


def main(env=os.environ, gh=None):
    owner = env.get("GITHUB_REPOSITORY_OWNER", "")
    guards = [(env.get("GITHUB_ACTIONS") == "true", "not running in GitHub Actions"),
              (env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "not a manual run"),
              (env.get("GITHUB_REF") == "refs/heads/main", "not running on main"),
              (bool(owner) and env.get("GITHUB_ACTOR") == owner, "actor is not the repository owner"),
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
