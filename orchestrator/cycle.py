"""Local, replayable SYNTHETIC orchestration cycle for T-003.

This is a synthetic test harness, not live agent automation. It drives the
fail-closed planner in ``orchestrator.state`` with two synthetic stand-ins
(an implementer and a reviewer) so that one task can go from a claim to a
single local READY_FOR_OWNER notification with no manual message relay.

Nothing here starts Claude or Codex, calls GitHub or any network service,
reads a secret, merges, or schedules anything. Activation of real agents is
reported separately by ``activation_status()`` and stays BLOCKED.

Identity checks compare synthetic fixture labels only. They are NOT
authenticated provenance: nothing proves which agent produced a review.

Replay:  python3 -m orchestrator.cycle [--out NEW_DIR_OUTSIDE_THE_CHECKOUT]
"""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, replace

from orchestrator.state import Snapshot, transition

PUBLIC_REPOSITORY = "cooljudge72-lgtm/Orchestrator-public-test"
SYNTHETIC_LABEL = "SYNTHETIC TEST - not live agent automation"
SYNTHETIC_PR_NUMBER = 9001  # synthetic; not a real pull request
VERDICTS = ("APPROVED", "CHANGES_REQUESTED")
_HEX = frozenset("0123456789abcdef")


def synthetic_sha(*parts):
    """Deterministic 40-hex value standing in for a commit SHA."""
    return hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()


def _is_sha(value):
    return type(value) is str and len(value) == 40 and set(value) <= _HEX


@dataclass(frozen=True)
class Identity:
    name: str        # e.g. "synthetic-implementer"
    role: str        # actor name used by orchestrator.state: claude / codex
    credential: str  # opaque label of the write credential; never a secret


def _valid_identity(value):
    return type(value) is Identity and all(
        type(field) is str and bool(field.strip())
        for field in (value.name, value.role, value.credential)
    )


@dataclass(frozen=True)
class Implementation:
    head_sha: str
    changed_files: object  # tuple of paths, or None when no path evidence


@dataclass(frozen=True)
class Review:
    event_id: str
    repository: str
    pr_number: int
    head_sha: str
    reviewer: Identity
    verdict: str
    findings: tuple = ()


class SyntheticImplementer:
    """Stand-in for the implementer: returns a new synthetic head per call."""

    def __init__(self, identity, files, report_paths=True):
        self.identity = identity
        self.files = tuple(files)
        self.report_paths = report_paths
        self.calls = []  # findings addressed by each call

    def implement(self, task_id, findings=()):
        self.calls.append(tuple(findings))
        head = synthetic_sha("implementation", task_id, str(len(self.calls)))
        return Implementation(head, self.files if self.report_paths else None)


class SyntheticReviewer:
    """Stand-in for the independent reviewer: verdicts follow a script."""

    def __init__(self, identity, verdicts=("CHANGES_REQUESTED", "APPROVED")):
        verdicts = tuple(verdicts)
        if not verdicts:
            raise ValueError("synthetic reviewer needs at least one verdict")
        self.identity = identity
        self.verdicts = verdicts
        self.calls = 0

    def review(self, repository, pr_number, head_sha):
        verdict = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        findings = (("synthetic finding %d" % self.calls,)
                    if verdict == "CHANGES_REQUESTED" else ())
        event_id = synthetic_sha("review", repository, str(pr_number),
                                 head_sha, str(self.calls))
        return Review(event_id, repository, pr_number, head_sha,
                      self.identity, verdict, findings)


class Orchestrator:
    """Routes synthetic results through ``orchestrator.state`` automatically.

    Every review must be bound to this coordinator's repository, PR number,
    current head SHA and REVIEWING state, and must come from the configured
    reviewer identity (synthetic labels, not authenticated provenance).

    Guarantee scope: event de-duplication and the single READY_FOR_OWNER
    notification hold only within ONE instance in ONE process, processing
    its inbox serially. All state is in memory. A new instance starts empty
    and can re-run the cycle and emit its own notification; concurrent or
    cross-restart delivery is not supported and is not claimed to be safe.

    Any adapter exception, missing or malformed result, or unexpected error
    at this boundary moves the snapshot to BLOCKED. Readiness is published
    after the inbox drains. Blocking withdraws the active local notice and
    records invalidation in the transcript; no external notice is revoked.
    """

    def __init__(self, *, repository, task_id, pr_number, base_sha,
                 allowed_paths, implementer, reviewer, ci_results,
                 claim_verified):
        self.repository = repository
        self.pr_number = pr_number
        self.allowed_paths = frozenset(allowed_paths)
        self.implementer = implementer
        self.reviewer = reviewer
        self.ci_results = ci_results  # head SHA -> True only if CI passed
        self.claim_verified = claim_verified
        self.snapshot = Snapshot(repository, task_id, base_sha, "CLAIMED")
        self.paths_verified = {}      # head SHA -> bool
        self.accepted = {}            # event_id -> accepted Review
        self.notified = set()
        self.notifications = []
        self.invalidated_notifications = []
        self.transcript = []
        self.inbox = []

    # -- public API --------------------------------------------------------

    def start(self):
        self.inbox.append(("start", None))
        return self.run()

    def receive(self, review):
        """Deliver an external review event (possibly a redelivery)."""
        self.inbox.append(("review", review))
        return self.run()

    def run(self):
        while self.inbox:
            kind, payload = self.inbox.pop(0)
            if self.snapshot.state == "BLOCKED":
                self._log("IGNORED_AFTER_BLOCKED", kind)
                continue
            try:
                getattr(self, "_on_" + kind)(payload)
            except Exception as exc:  # fail closed at the boundary
                self._block("coordinator error: %s" % type(exc).__name__)
        key = (self.repository, self.pr_number, self.snapshot.head_sha)
        if self.snapshot.state == "READY_FOR_OWNER" and key not in self.notified:
            self._notify()
        return self.snapshot

    # -- handlers ----------------------------------------------------------

    def _on_start(self, _):
        if (self.claim_verified is not True or type(self.repository) is not str
                or type(self.ci_results) is not dict
                or type(self.pr_number) is not int or self.pr_number <= 0
                or type(self.snapshot.task_id) is not str
                or not self.snapshot.task_id.strip()
                or not _is_sha(self.snapshot.head_sha)
                or not _valid_identity(self.implementer.identity)
                or not _valid_identity(self.reviewer.identity)):
            self._block("invalid cycle fixture")
            return
        self._apply("CLAIM_ACCEPTED", actor="owner")
        if self.snapshot.state == "IMPLEMENTING":
            self._request_implementation(())

    def _on_implemented(self, impl):
        if type(impl) is not Implementation or not _is_sha(impl.head_sha):
            self._block("implementer returned no valid result")
            return
        files = impl.changed_files
        self.paths_verified[impl.head_sha] = (
            type(files) in (tuple, list) and len(files) > 0
            and all(type(path) is str and path in self.allowed_paths
                    for path in files))
        self._apply("IMPLEMENTED", actor=self.implementer.identity.role,
                    head_sha=impl.head_sha)
        if self.snapshot.state == "REVIEWING":
            ok, review = self._call("reviewer", self.reviewer.review,
                                    self.repository, self.pr_number,
                                    self.snapshot.head_sha)
            if ok:
                self.inbox.append(("review", review))

    def _on_review(self, review):
        if (type(review) is not Review or not _is_sha(review.event_id)
                or type(review.repository) is not str
                or type(review.pr_number) is not int or review.pr_number <= 0
                or not _is_sha(review.head_sha)
                or not _valid_identity(review.reviewer)
                or type(review.verdict) is not str or review.verdict not in VERDICTS
                or type(review.findings) is not tuple
                or any(type(item) is not str for item in review.findings)):
            self._block("reviewer returned no valid result")
            return
        # An already accepted event id: identical retry is a no-op, any
        # different content under the same id is a conflict.
        prior = self.accepted.get(review.event_id)
        if prior is not None:
            if prior == review:
                self._log("DUPLICATE_IGNORED", review.event_id[:12])
            else:
                self._block("conflicting reuse of event id %s"
                            % review.event_id[:12])
            return
        # Validate everything before the event id is consumed.
        if review.repository != self.repository:
            self._block("review for another repository")
            return
        if review.reviewer != self.reviewer.identity:
            self._block("review not from the configured reviewer")
            return
        if (review.pr_number != self.pr_number
                or review.head_sha != self.snapshot.head_sha
                or self.snapshot.state != "REVIEWING"):
            self._log("REJECTED_STALE_OR_UNBOUND",
                      "pr=%s head=%s" % (review.pr_number,
                                         str(review.head_sha)[:12]))
            return
        impl_id = self.implementer.identity
        independent = (review.reviewer.role == "codex"
                       and review.reviewer.name != impl_id.name
                       and review.reviewer.credential != impl_id.credential)
        event = ("REVIEW_APPROVED" if review.verdict == "APPROVED"
                 else "REVIEW_CHANGES")
        self._apply(event, actor=review.reviewer.role,
                    reviewer_independent=independent,
                    detail="%s pr=%d head=%s" % (review.repository,
                                                 review.pr_number,
                                                 review.head_sha[:12]))
        if self.snapshot.state != "BLOCKED":
            self.accepted[review.event_id] = review
        if self.snapshot.state == "REVISING":
            self._request_implementation(review.findings)

    # -- helpers -----------------------------------------------------------

    def _request_implementation(self, findings):
        ok, impl = self._call("implementer", self.implementer.implement,
                              self.snapshot.task_id, findings)
        if ok:
            self.inbox.append(("implemented", impl))

    def _call(self, role, func, *args):
        """Call an adapter; any exception blocks (type name only, no text)."""
        try:
            return True, func(*args)
        except Exception as exc:
            self._block("%s failure: %s" % (role, type(exc).__name__))
            return False, None

    def _block(self, detail):
        """Enter BLOCKED directly; never calls transition() or reads fixtures.

        This is the fail-closed path for boundary errors, so it must not
        depend on anything that could itself be malformed and raise.
        """
        self.snapshot = replace(self.snapshot, state="BLOCKED")
        self._log("BLOCK", detail, actor="coordinator")
        self._invalidate_readiness()

    def _invalidate_readiness(self):
        if self.snapshot.state == "BLOCKED" and self.notifications:
            self.invalidated_notifications.extend(self.notifications)
            self.notifications.clear()
            self._log("READINESS_INVALIDATED", "local synthetic notice withdrawn")

    def _apply(self, event, *, actor, head_sha=None, reviewer_independent=False,
               detail=""):
        head = self.snapshot.head_sha if head_sha is None else head_sha
        self.snapshot = transition(
            self.snapshot, event, repository=self.repository, head_sha=head,
            actor=actor, ci_passed=self.ci_results.get(head) is True,
            reviewer_independent=reviewer_independent,
            # Only real path evidence counts; none exists before the first
            # implementation (the planner exempts CLAIM_ACCEPTED, S2-1).
            allowed_paths=self.paths_verified.get(head) is True,
            claim_verified=self.claim_verified is True)
        self._log(event, detail, actor=actor)
        self._invalidate_readiness()

    def _notify(self):
        if self.snapshot.state != "READY_FOR_OWNER":
            return
        key = (self.repository, self.pr_number, self.snapshot.head_sha)
        if key in self.notified:
            self._log("NOTIFICATION_SUPPRESSED", "already sent")
            return
        self.notified.add(key)
        self.notifications.append({
            "label": SYNTHETIC_LABEL,
            "status": "READY_FOR_OWNER",
            "repository": key[0],
            "pr_number": key[1],
            "head_sha": key[2],
            "task_id": self.snapshot.task_id,
            "revision_rounds": self.snapshot.revision_rounds,
            "merge": "owner only; nothing was merged",
        })
        self._log("NOTIFIED", "READY_FOR_OWNER")

    def _log(self, event, detail="", actor=None):
        self.transcript.append({
            "event": event,
            "actor": actor,
            "state": self.snapshot.state,
            "head_sha": self.snapshot.head_sha,
            "revision_rounds": self.snapshot.revision_rounds,
            "detail": detail,
        })


def activation_status():
    """Status of LIVE agent activation, kept separate from synthetic results.

    The reasons are static prerequisites that are known to be unmet, not
    runtime checks. No approved agent runtime exists in this repository, so
    activation is always BLOCKED; the synthetic cycle does not change this.
    """
    return {
        "status": "BLOCKED",
        "reasons": [
            "no approved live runtime: Claude and Codex are not executed; "
            "only synthetic stand-ins are wired",
            "no independent reviewer credential separate from the "
            "implementer's write identity (docs/PILOT.md, B1); reviewer "
            "binding checks synthetic labels, not authenticated provenance",
            "owner-only merge is procedural, not technically enforced "
            "beyond the ruleset",
            "no T-003 claim evidence (refs/lockcheck/task-T-003) or "
            "tasks/T-003.json on main",
            "claim, changed paths, current HEAD and CI are synthetic "
            "inputs, not read from GitHub",
            "event de-duplication is in-memory and single-instance; no "
            "persistent or atomic store, so restart- and concurrency-safe "
            "delivery is unverified",
            "external execution, credentials and scheduling need separate "
            "explicit owner approval (Issue #9, step 5)",
        ],
    }


def default_cycle(**overrides):
    """Build the standard synthetic scenario; keyword overrides for tests."""
    task_id = overrides.pop("task_id", "T-003")
    implementer = overrides.pop("implementer", SyntheticImplementer(
        Identity("synthetic-implementer", "claude", "cred-implementer"),
        files=("orchestrator/synthetic_task.py",
               "tests/test_synthetic_task.py")))
    reviewer = overrides.pop("reviewer", SyntheticReviewer(
        Identity("synthetic-reviewer", "codex", "cred-reviewer")))
    ci_results = overrides.pop("ci_results", None)
    if ci_results is None:
        ci_results = {synthetic_sha("implementation", task_id, str(n)): True
                      for n in range(1, 4)}
    options = dict(
        repository=PUBLIC_REPOSITORY, task_id=task_id,
        pr_number=SYNTHETIC_PR_NUMBER,
        base_sha=synthetic_sha("base", task_id),
        allowed_paths=("orchestrator/synthetic_task.py",
                       "tests/test_synthetic_task.py"),
        implementer=implementer, reviewer=reviewer, ci_results=ci_results,
        claim_verified=True)
    options.update(overrides)
    return Orchestrator(**options)


def run_synthetic_cycle():
    orch = default_cycle()
    orch.start()
    return {
        "label": SYNTHETIC_LABEL,
        "synthetic_cycle": {
            "result": orch.snapshot.state,
            "snapshot": asdict(orch.snapshot),
            "implementer_calls": len(orch.implementer.calls),
            "reviewer_calls": orch.reviewer.calls,
            "notifications": orch.notifications,
            "invalidated_notifications": orch.invalidated_notifications,
            "transcript": orch.transcript,
        },
        "activation": activation_status(),
    }


# -- local report output -----------------------------------------------------


class OutputError(Exception):
    """The requested output destination is refused."""


def _repository_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.realpath(os.path.join(here, os.pardir))


def _open_output_parent(path, checkout):
    """Open each absolute component without following any symlink."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(os.path.sep, flags)
    try:
        for part in path.split(os.path.sep)[1:]:
            if not part:
                continue
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            if os.path.samestat(os.fstat(fd), checkout):
                raise OutputError("output path must be outside the repository checkout")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _no_replace_rename():
    if sys.platform != "linux" or not shutil.rmtree.avoids_symlink_attacks:
        raise OutputError("safe output publication is unavailable on this platform")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        raise OutputError("atomic no-replacement rename is unavailable") from None
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int

    def publish(fd, source, destination):
        if rename(fd, os.fsencode(source), fd, os.fsencode(destination), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))

    return publish


def write_outputs(out_dir, files):
    """Publish a complete report with Linux renameat2(RENAME_NOREPLACE).

    Output ancestors must be real directories. The parent is pinned by FD
    for staging, publication and cleanup, even if its pathname is replaced.
    Use an owner-controlled parent: this is not an isolation boundary
    against another process with the same UID or a privileged process.
    Unsupported platforms and filesystems fail closed. Stdout is portable.
    """
    publish = _no_replace_rename()
    target = os.path.abspath(out_dir)
    parent, name = os.path.split(target)
    if not name:
        raise OutputError("output path already exists; refusing to overwrite")
    root = _repository_root()
    if os.path.commonpath([parent, root]) == root:
        raise OutputError("output path must be outside the repository checkout")
    try:
        parent_fd = _open_output_parent(parent, os.stat(root))
    except FileNotFoundError:
        raise OutputError("parent directory of the output path does not exist") from None
    try:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OutputError("output path already exists; refusing to overwrite")
        staging = ".cycle-out-" + uuid.uuid4().hex
        os.mkdir(staging, 0o700, dir_fd=parent_fd)
        try:
            stage_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=parent_fd)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                for filename, content in files:
                    if not filename or os.path.basename(filename) != filename or filename in (".", ".."):
                        raise OutputError("invalid report filename")
                    fd = os.open(filename, flags, 0o644, dir_fd=stage_fd)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(content)
                current_fd = _open_output_parent(parent, os.stat(root))
                try:
                    if not os.path.samestat(os.fstat(parent_fd), os.fstat(current_fd)):
                        raise OutputError("output parent changed during write")
                finally:
                    os.close(current_fd)
                publish(parent_fd, staging, name)
            finally:
                os.close(stage_fd)
        except BaseException:
            shutil.rmtree(staging, dir_fd=parent_fd)
            raise
    finally:
        os.close(parent_fd)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=SYNTHETIC_LABEL)
    parser.add_argument("--out", help="NEW directory, outside the checkout, "
                        "for cycle.json and notifications.jsonl")
    args = parser.parse_args(argv)
    report = run_synthetic_cycle()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        notes = "".join(json.dumps(note, sort_keys=True) + "\n"
                        for note in report["synthetic_cycle"]["notifications"])
        try:
            write_outputs(args.out, [("cycle.json", text + "\n"),
                                     ("notifications.jsonl", notes)])
        except (OutputError, OSError) as exc:
            print("error: %s" % (exc if isinstance(exc, OutputError)
                                 else type(exc).__name__), file=sys.stderr)
            return 2
    print(text)
    cycle = report["synthetic_cycle"]
    ok = (cycle["result"] == "READY_FOR_OWNER"
          and len(cycle["notifications"]) == 1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
