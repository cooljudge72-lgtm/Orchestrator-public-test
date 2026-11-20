"""Create-only git refs as locks.

POST /repos/{repo}/git/refs answers 422 "Reference already exists" if the ref exists, so exactly
one caller should be able to create a given ref. Only that exact answer means "held"; any other
error is raised so callers fail closed. Refs are only ever created under refs/lockcheck/.
"""
import json
import urllib.error

ACQUIRED, HELD = "acquired", "held"
NAMESPACE = "refs/lockcheck/"


class LockError(RuntimeError):
    pass


def check_ref(ref):
    tail = ref[len(NAMESPACE):] if ref.startswith(NAMESPACE) else ""
    if not tail or ".." in tail or any(c in tail for c in " ~^:?*[\\"):
        raise LockError("lock refs must be plain names under refs/lockcheck/")
    return ref


def already_exists(err):
    if not isinstance(err, urllib.error.HTTPError) or err.code != 422:
        return False
    try:
        return json.loads(err.read() or b"{}").get("message") == "Reference already exists"
    except ValueError:
        return False


def acquire(gh, repo, ref, commit_sha):
    check_ref(ref)
    try:
        gh.call("POST", f"/repos/{repo}/git/refs", {"ref": ref, "sha": commit_sha})
        return ACQUIRED
    except urllib.error.HTTPError as err:
        if already_exists(err):
            return HELD
        raise LockError(f"creating {ref} failed with HTTP {err.code}") from None
