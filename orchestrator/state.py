"""Fail-closed, pure orchestration planner. No agent execution or GitHub writes.

This module does not start Claude or Codex. A separate, explicitly approved
runtime must provide authenticated, independent agent results.
"""
from dataclasses import dataclass

STATES = frozenset({"CLAIMED", "IMPLEMENTING", "REVIEWING", "REVISING", "READY_FOR_OWNER", "BLOCKED"})
MAX_ROUNDS = 2


@dataclass(frozen=True)
class Snapshot:
    repository: str
    task_id: str
    head_sha: str
    state: str
    revision_rounds: int = 0


def transition(snapshot, event, *, repository, head_sha, actor, ci_passed=False,
               reviewer_independent=False, allowed_paths=True, claim_verified=False):
    """Return a new snapshot; any integrity ambiguity blocks instead of acting.

    Events are observations, not commands to external agents. Only the owner can
    merge outside this module; MERGE is never a supported event.
    """
    if not isinstance(snapshot, Snapshot):
        raise TypeError("snapshot must be Snapshot")
    if snapshot.state not in STATES or snapshot.state == "BLOCKED":
        return _blocked(snapshot)
    if (repository != snapshot.repository or not repository.endswith("/Orchestrator-public-test")
            or snapshot.repository != "cooljudge72-lgtm/Orchestrator-public-test"
            or not claim_verified or not allowed_paths
            or not isinstance(head_sha, str) or len(head_sha) != 40
            or any(c not in "0123456789abcdef" for c in head_sha)
            or snapshot.revision_rounds < 0 or snapshot.revision_rounds > MAX_ROUNDS):
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
        if head_sha != snapshot.head_sha or not reviewer_independent:
            return _blocked(snapshot)
        if snapshot.revision_rounds >= MAX_ROUNDS:
            return _blocked(snapshot)
        return _replace(snapshot, "REVISING", snapshot.revision_rounds + 1)
    if event == "REVIEW_APPROVED" and snapshot.state == "REVIEWING" and actor == "codex":
        if head_sha != snapshot.head_sha or not reviewer_independent or not ci_passed:
            return _blocked(snapshot)
        return _replace(snapshot, "READY_FOR_OWNER")
    return _blocked(snapshot)


def _replace(s, state, rounds=None):
    return Snapshot(s.repository, s.task_id, s.head_sha, state,
                    s.revision_rounds if rounds is None else rounds)


def _blocked(s):
    return _replace(s, "BLOCKED")
