"""Task claims: one atomic, identity-carrying claim per task.

A claim is the ref  refs/lockcheck/task-<TASK_ID>  created with GitHub's create-reference call,
whose create-if-absent behaviour was verified (10 concurrent creates -> 1 acquired, 9 held). The
ref points at an annotated tag object whose message records the execution context of the run that
took the claim (task, agent, repository, actor, triggering actor, workflow path, ref, commit, run id
and run attempt). The status check later verifies that context against the Actions API, so a
claim is only trusted if a real claim-task run by the owner on main created it.

Claims are PERMANENT in this pilot (never deleted by automation); see docs/PILOT.md.
Each claim attempt creates a tag object first; a losing attempt leaves that tag object
unreferenced (metadata only) until GitHub garbage-collects it.
"""
import json
import os
import re
import sys
import urllib.error
from pathlib import Path

from .lock import ACQUIRED, HELD, LockError, already_exists, check_ref

TASK_ID = re.compile(r"T-\d{3}")
AGENTS = {"claude"}
CLAIM_WORKFLOW = ".github/workflows/claim-task.yml"


def claim_ref(task_id):
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise LockError("task id must look like T-001")
    return check_ref(f"refs/lockcheck/task-{task_id}")


def workflow_path(workflow_ref, repo):
    """GITHUB_WORKFLOW_REF is 'owner/repo/.github/workflows/x.yml@refs/heads/main'."""
    path = (workflow_ref or "").split("@", 1)[0]
    prefix = repo.lower() + "/"
    return path[len(prefix):] if path.lower().startswith(prefix) else None


def build_identity(env, task):
    repo = env["GITHUB_REPOSITORY"]
    return {"task_id": task["task_id"], "agent": task["agent"], "repo": repo,
            "actor": env["GITHUB_ACTOR"], "triggering_actor": env.get("GITHUB_TRIGGERING_ACTOR", ""),
            "workflow": workflow_path(env.get("GITHUB_WORKFLOW_REF"), repo), "ref": env["GITHUB_REF"],
            "sha": env["GITHUB_SHA"], "run_id": env["GITHUB_RUN_ID"],
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT", "1")}


def acquire_claim(gh, repo, identity):
    """Create the tag object, then the claim ref pointing at it. ACQUIRED / HELD / LockError."""
    ref = claim_ref(identity["task_id"])
    try:
        tag = gh.call("POST", f"/repos/{repo}/git/tags", {
            "tag": f"claim-{identity['task_id']}", "message": json.dumps(identity, sort_keys=True),
            "object": identity["sha"], "type": "commit"})
        gh.call("POST", f"/repos/{repo}/git/refs", {"ref": ref, "sha": tag["sha"]})
        return ACQUIRED
    except urllib.error.HTTPError as err:
        if already_exists(err):
            return HELD
        raise LockError(f"claiming {ref} failed with HTTP {err.code}") from None


def check_context(env, task_id, agent, task):
    """Return '' if this run may take the claim, else the reason. Fail closed."""
    owner = env.get("GITHUB_REPOSITORY_OWNER", "")
    checks = [
        (env.get("GITHUB_ACTIONS") == "true", "not running in GitHub Actions"),
        (env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "not a manual workflow_dispatch run"),
        (env.get("GITHUB_REF") == "refs/heads/main", "not running on main"),
        (bool(owner) and env.get("GITHUB_ACTOR") == owner, "actor is not the repository owner"),
        (env.get("GITHUB_TRIGGERING_ACTOR") == owner, "triggering actor is not the repository owner"),
        (workflow_path(env.get("GITHUB_WORKFLOW_REF"), env.get("GITHUB_REPOSITORY", "")) == CLAIM_WORKFLOW,
         "not the claim-task workflow"),
        (isinstance(task_id, str) and bool(TASK_ID.fullmatch(task_id)), "invalid task id"),
        (agent in AGENTS, "agent is not allowed"),
        (task is not None, "no task definition on main for this task id"),
    ]
    for ok, reason in checks:
        if not ok:
            return reason
    if task.get("task_id") != task_id or task.get("agent") != agent:
        return "task definition does not match the requested task/agent"
    return ""


def load_task(task_id, root="."):
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        return None
    path = Path(root) / "tasks" / f"{task_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(env=os.environ, gh=None, root="."):
    task_id, agent = env.get("TASK_ID", ""), env.get("AGENT", "")
    task = load_task(task_id, root)
    problem = check_context(env, task_id, agent, task)
    if problem:
        print(f"CLAIM REFUSED: {problem}")
        return 2
    if gh is None:
        from .github_api import GitHub
        gh = GitHub(env["GITHUB_TOKEN"])
    identity = build_identity(env, task)
    try:
        result = acquire_claim(gh, env["GITHUB_REPOSITORY"], identity)
    except LockError as err:
        print(f"CLAIM FAILED: {err}")
        return 1
    print(f"CLAIM {task_id}: {result.upper()}")
    return 0 if result == ACQUIRED else 1


if __name__ == "__main__":
    sys.exit(main())
