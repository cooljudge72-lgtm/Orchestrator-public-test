"""Fail-closed, pure orchestration planner. No agent execution or GitHub writes.

This module does not start Claude or Codex. A separate, explicitly approved
runtime must provide authenticated, independent agent results.
"""
from dataclasses import dataclass

STATES = frozenset({"CLAIMED", "IMPLEMENTING", "REVIEWING", "REVISING", "READY_FOR_OWNER", "BLOCKED"})
MAX_ROUNDS = 2
PUBLIC_REPOSITORY = "cooljudge72-lgtm/Orchestrator-public-test"


@dataclass(frozen=True)
class Snapshot:
    repository: str
    task_id: str
    head_sha: str
    state: str
    revision_rounds: int = 0


def transition(snapshot, event, *, repository=None, head_sha, actor, ci_passed=False,
               reviewer_independent=False, allowed_paths=False, claim_verified=False):
    """Return a new snapshot; any integrity ambiguity blocks instead of acting.

    Events are observations, not commands to external agents. Only the owner can
    merge outside this module; MERGE is never a supported event.

    The four verification gates (ci_passed, reviewer_independent, allowed_paths,
    claim_verified) default to False and pass only for the exact boolean True.
    An omitted, False, non-boolean or merely truthy value blocks.

    The repository must be exactly PUBLIC_REPOSITORY (a str) in both the call
    and the snapshot, and revision_rounds must be an int (not bool) within
    0..MAX_ROUNDS. snapshot.state must be a str in STATES. Missing or
    malformed values block; they never raise.

    CLAIM_ACCEPTED is the only event exempt from requiring allowed_paths to be
    True: no implementation (and so no path evidence) exists yet. The gate must
    still be a bool, and every later gated event requires allowed_paths True.
    """
    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")
    if (type(snapshot.state) is not str or snapshot.state not in STATES
            or snapshot.state == "BLOCKED"):
        return _blocked(snapshot)
    if any(type(gate) is not bool for gate in (ci_passed, reviewer_independent,
                                                allowed_paths, claim_verified)):
        return _blocked(snapshot)  # malformed verification result
    if (type(repository) is not str or repository != PUBLIC_REPOSITORY
            or type(snapshot.repository) is not str
            or snapshot.repository != PUBLIC_REPOSITORY
            or claim_verified is not True
            or (event != "CLAIM_ACCEPTED" and allowed_paths is not True)
            or not isinstance(head_sha, str) or len(head_sha) != 40
            or any(c not in "0123456789abcdef" for c in head_sha)
            or type(snapshot.revision_rounds) is not int
            or not 0 <= snapshot.revision_rounds <= MAX_ROUNDS):
        return _blocked(snapshot)
    if event == "BLOCK":
        return _blocked(snapshot)
    if event == "CLAIM_ACCEPTED" and snapshot.state == "CLAIMED" and actor == "owner":
        return _replace(snapshot, "IMPLEMENTING")
    if event == "IMPLEMENTED" and snapshot.state in ("IMPLEMENTING", "REVISING") and actor == "claude":
        if head_sha == snapshot.head_sha:
            return _blocked(snapshot)  # require a new commit for implementation
        return Snapshot(repository, snapshot.task_id, head_sha, "REVIEWING", snapshot.revision_rounds)
    if event == "REVIEW_CHANGES" and snapshot.state == "REVIEWING" and actor == "codex":
        if head_sha != snapshot.head_sha or reviewer_independent is not True:
            return _blocked(snapshot)
        if snapshot.revision_rounds >= MAX_ROUNDS:
            return _blocked(snapshot)
        return _replace(snapshot, "REVISING", snapshot.revision_rounds + 1)
    if event == "REVIEW_APPROVED" and snapshot.state == "REVIEWING" and actor == "codex":
        if (head_sha != snapshot.head_sha or reviewer_independent is not True
                or ci_passed is not True):
            return _blocked(snapshot)
        return _replace(snapshot, "READY_FOR_OWNER")
    return _blocked(snapshot)


def _replace(s, state, rounds=None):
    return Snapshot(s.repository, s.task_id, s.head_sha, state,
                    s.revision_rounds if rounds is None else rounds)


def _blocked(s):
    return _replace(s, "BLOCKED")
