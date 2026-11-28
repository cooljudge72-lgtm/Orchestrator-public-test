"""SYNTHETIC end-to-end tests for the local T-003 orchestration cycle.

Synthetic stand-ins only: no agent, GitHub or network call is made. These
tests prove the local cycle logic; they do not show live agent automation,
whose activation status stays BLOCKED.
"""

import io
import itertools
import json
import os
import tempfile
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from unittest import mock

from orchestrator import cycle
from orchestrator.cycle import (
    PUBLIC_REPOSITORY, SYNTHETIC_PR_NUMBER, Identity, SyntheticImplementer,
    SyntheticReviewer, activation_status, default_cycle, synthetic_sha)

HEAD1 = synthetic_sha("implementation", "T-003", "1")
HEAD2 = synthetic_sha("implementation", "T-003", "2")


def events(orch):
    return [entry["event"] for entry in orch.transcript]


class SyntheticCycleTests(unittest.TestCase):
    def test_full_cycle_without_manual_relay(self):
        orch = default_cycle()
        orch.start()
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(orch.snapshot.head_sha, HEAD2)
        self.assertEqual(orch.snapshot.revision_rounds, 1)
        self.assertEqual(events(orch), [
            "CLAIM_ACCEPTED", "IMPLEMENTED", "REVIEW_CHANGES", "IMPLEMENTED",
            "REVIEW_APPROVED", "NOTIFIED"])
        states = [e["state"] for e in orch.transcript]
        self.assertEqual(states, ["IMPLEMENTING", "REVIEWING", "REVISING",
                                  "REVIEWING", "READY_FOR_OWNER",
                                  "READY_FOR_OWNER"])
        # The fix addressed the review findings and produced a new head.
        self.assertEqual(orch.implementer.calls,
                         [(), ("synthetic finding 1",)])
        self.assertEqual(orch.reviewer.calls, 2)
        self.assertEqual(len(orch.notifications), 1)
        note = orch.notifications[0]
        self.assertEqual(note["status"], "READY_FOR_OWNER")
        self.assertEqual((note["repository"], note["pr_number"],
                          note["head_sha"]),
                         (PUBLIC_REPOSITORY, SYNTHETIC_PR_NUMBER, HEAD2))
        self.assertIn("SYNTHETIC", note["label"])
        self.assertIn("nothing was merged", note["merge"])

    def test_each_review_bound_to_repo_pr_and_head(self):
        orch = default_cycle()
        orch.start()
        reviews = [e["detail"] for e in orch.transcript
                   if e["event"].startswith("REVIEW_")]
        self.assertEqual(reviews, [
            "%s pr=%d head=%s" % (PUBLIC_REPOSITORY, SYNTHETIC_PR_NUMBER,
                                  HEAD1[:12]),
            "%s pr=%d head=%s" % (PUBLIC_REPOSITORY, SYNTHETIC_PR_NUMBER,
                                  HEAD2[:12])])

    def test_replay_is_deterministic(self):
        self.assertEqual(cycle.run_synthetic_cycle(),
                         cycle.run_synthetic_cycle())


class IdempotencyTests(unittest.TestCase):
    def _review(self, orch, head, verdict, call):
        return cycle.Review(
            synthetic_sha("review", PUBLIC_REPOSITORY,
                          str(SYNTHETIC_PR_NUMBER), head, str(call)),
            PUBLIC_REPOSITORY, SYNTHETIC_PR_NUMBER, head,
            orch.reviewer.identity, verdict,
            ("synthetic finding %d" % call,)
            if verdict == "CHANGES_REQUESTED" else ())

    def test_redelivered_changes_request_does_not_repeat_fix(self):
        orch = default_cycle()
        orch.start()
        orch.receive(self._review(orch, HEAD1, "CHANGES_REQUESTED", 1))
        self.assertEqual(len(orch.implementer.calls), 2)
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(events(orch)[-1], "DUPLICATE_IGNORED")

    def test_redelivered_approval_does_not_repeat_notification(self):
        orch = default_cycle()
        orch.start()
        for _ in range(3):
            orch.receive(self._review(orch, HEAD2, "APPROVED", 2))
        self.assertEqual(len(orch.notifications), 1)
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(len(orch.implementer.calls), 2)

    def test_notification_sent_once_per_head(self):
        orch = default_cycle()
        orch.start()
        orch._notify()
        self.assertEqual(len(orch.notifications), 1)
        self.assertEqual(events(orch)[-1], "NOTIFICATION_SUPPRESSED")

    def test_stale_head_review_not_accepted(self):
        # Hold the automatic re-review so a late result for the old head
        # arrives first; it must be rejected, not acted on.
        orch = default_cycle()
        orch.inbox.append(("start", None))
        while not (orch.snapshot.state == "REVIEWING"
                   and orch.snapshot.head_sha == HEAD2):
            kind, payload = orch.inbox.pop(0)
            getattr(orch, "_on_" + kind)(payload)
        pending = list(orch.inbox)
        orch.inbox.clear()
        stale = self._review(orch, HEAD1, "APPROVED", 99)
        orch.receive(stale)
        self.assertEqual(orch.snapshot.state, "REVIEWING")
        self.assertEqual(orch.snapshot.head_sha, HEAD2)
        self.assertEqual(events(orch)[-1], "REJECTED_STALE_OR_UNBOUND")
        self.assertEqual(orch.notifications, [])
        orch.inbox.extend(pending)
        orch.run()
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(orch.notifications[0]["head_sha"], HEAD2)

    def test_review_for_another_pr_not_accepted(self):
        orch = default_cycle()
        orch.inbox.append(("start", None))
        for _ in range(2):  # start, implemented -> REVIEWING head 1
            kind, payload = orch.inbox.pop(0)
            getattr(orch, "_on_" + kind)(payload)
        orch.inbox.clear()
        other = replace(self._review(orch, HEAD1, "APPROVED", 1),
                        pr_number=SYNTHETIC_PR_NUMBER + 1, event_id="a" * 40)
        orch.receive(other)
        self.assertEqual(orch.snapshot.state, "REVIEWING")
        self.assertEqual(events(orch)[-1], "REJECTED_STALE_OR_UNBOUND")


class FailClosedTests(unittest.TestCase):
    def _assert_blocked(self, orch):
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])

    def test_wrong_repository_blocked(self):
        for repo in ("someone-else/Orchestrator-public-test",
                     "cooljudge72-lgtm/private-judicial", ""):
            with self.subTest(repo=repo):
                orch = default_cycle(repository=repo)
                orch.start()
                self._assert_blocked(orch)
                self.assertEqual(orch.implementer.calls, [])

    def test_review_from_wrong_repository_blocked(self):
        orch = default_cycle()
        orch.inbox.append(("start", None))
        for _ in range(2):
            kind, payload = orch.inbox.pop(0)
            getattr(orch, "_on_" + kind)(payload)
        review = orch.inbox.pop(0)[1]
        orch.receive(replace(review, repository="someone/other-repo"))
        self._assert_blocked(orch)

    def test_missing_claim_evidence_blocked(self):
        orch = default_cycle(claim_verified=False)
        orch.start()
        self._assert_blocked(orch)
        self.assertEqual(orch.implementer.calls, [])

    def test_missing_path_evidence_blocked(self):
        implementer = SyntheticImplementer(
            Identity("synthetic-implementer", "claude", "cred-implementer"),
            files=("orchestrator/synthetic_task.py",), report_paths=False)
        orch = default_cycle(implementer=implementer)
        orch.start()
        self._assert_blocked(orch)
        self.assertEqual(orch.reviewer.calls, 0)

    def test_disallowed_path_blocked(self):
        implementer = SyntheticImplementer(
            Identity("synthetic-implementer", "claude", "cred-implementer"),
            files=("orchestrator/synthetic_task.py", ".github/workflows/x.yml"))
        orch = default_cycle(implementer=implementer)
        orch.start()
        self._assert_blocked(orch)

    def test_self_review_blocked(self):
        implementer_id = Identity("synthetic-implementer", "claude",
                                  "cred-implementer")
        for reviewer_id in (
                implementer_id,
                Identity("synthetic-implementer", "codex", "cred-reviewer"),
                Identity("synthetic-reviewer", "codex", "cred-implementer")):
            with self.subTest(reviewer=reviewer_id):
                orch = default_cycle(
                    implementer=SyntheticImplementer(
                        implementer_id,
                        files=("orchestrator/synthetic_task.py",)),
                    reviewer=SyntheticReviewer(reviewer_id))
                orch.start()
                self._assert_blocked(orch)

    def test_approval_without_successful_ci_blocked(self):
        for ci in ({HEAD1: True}, {HEAD1: True, HEAD2: False},
                   {HEAD1: True, HEAD2: "success"}):
            with self.subTest(ci=ci):
                orch = default_cycle(ci_results=ci)
                orch.start()
                self._assert_blocked(orch)
                self.assertEqual(events(orch)[-1], "REVIEW_APPROVED")

    def test_more_than_two_revision_rounds_blocked(self):
        orch = default_cycle(reviewer=SyntheticReviewer(
            Identity("synthetic-reviewer", "codex", "cred-reviewer"),
            verdicts=("CHANGES_REQUESTED",)))
        orch.start()
        self._assert_blocked(orch)
        self.assertEqual(len(orch.implementer.calls), 3)  # initial + 2 fixes
        self.assertEqual(orch.reviewer.calls, 3)
        self.assertEqual(orch.snapshot.revision_rounds, 2)

    def test_events_after_blocked_are_ignored(self):
        orch = default_cycle(claim_verified=False)
        orch.start()
        orch.receive(cycle.Review("y" * 40, PUBLIC_REPOSITORY,
                                  SYNTHETIC_PR_NUMBER, HEAD1,
                                  orch.reviewer.identity, "APPROVED"))
        self._assert_blocked(orch)
        self.assertEqual(events(orch)[-1], "IGNORED_AFTER_BLOCKED")


class ActivationStatusTests(unittest.TestCase):
    def test_activation_blocked_and_separate_from_synthetic_result(self):
        report = cycle.run_synthetic_cycle()
        self.assertEqual(report["synthetic_cycle"]["result"],
                         "READY_FOR_OWNER")
        self.assertEqual(report["activation"]["status"], "BLOCKED")
        self.assertTrue(report["activation"]["reasons"])
        self.assertIn("SYNTHETIC", report["label"])
        self.assertEqual(activation_status()["status"], "BLOCKED")

    @unittest.skipUnless(sys.platform == "linux", "atomic output requires Linux")
    def test_cli_writes_local_files_and_reports_blocked(self):
        # --out must now name a NEW directory (finding 5); the original
        # test used an existing temporary directory as the target.
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(os.path.realpath(tmp), "report")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cycle.main(["--out", out])
            self.assertEqual(code, 0)
            report = json.loads(buffer.getvalue())
            self.assertEqual(report["activation"]["status"], "BLOCKED")
            with open(os.path.join(out, "notifications.jsonl"),
                      encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["status"],
                             "READY_FOR_OWNER")
            with open(os.path.join(out, "cycle.json"),
                      encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), report)


# ---------------------------------------------------------------------------
# Regression tests for the Codex review findings (all fixtures synthetic).
# ---------------------------------------------------------------------------

IMPLEMENTER_ID = Identity("synthetic-implementer", "claude", "cred-implementer")
REVIEWER_ID = Identity("synthetic-reviewer", "codex", "cred-reviewer")
FILES = ("orchestrator/synthetic_task.py", "tests/test_synthetic_task.py")
VERDICTS_UNDER_TEST = ("APPROVED", "CHANGES_REQUESTED")


def drive_until(orch, predicate):
    """Process inbox items one at a time until ``predicate(orch)`` holds."""
    if not orch.inbox and orch.snapshot.state == "CLAIMED":
        orch.inbox.append(("start", None))
    while not predicate(orch):
        kind, payload = orch.inbox.pop(0)
        getattr(orch, "_on_" + kind)(payload)


def pending_review(orch):
    return (orch.snapshot.state == "REVIEWING"
            and orch.inbox and orch.inbox[0][0] == "review")


def synthetic_review(head, verdict, *, reviewer=REVIEWER_ID, call=1,
                     pr_number=SYNTHETIC_PR_NUMBER, event_id=None,
                     repository=PUBLIC_REPOSITORY):
    return cycle.Review(
        event_id or synthetic_sha("review", repository, str(pr_number), head,
                                  str(call)),
        repository, pr_number, head, reviewer, verdict,
        ("synthetic finding %d" % call,)
        if verdict == "CHANGES_REQUESTED" else ())


def details(orch):
    return [entry["detail"] for entry in orch.transcript]


class ReviewerBindingTests(unittest.TestCase):
    """Finding 1 (high): reviews must come from the configured reviewer.

    This compares synthetic identity labels only; it is not authenticated
    provenance for live operation.
    """

    FOREIGN = (
        Identity("other", "codex", "other-label"),
        Identity("synthetic-reviewer", "codex", "other-label"),
        Identity("other", "codex", "cred-reviewer"),
        Identity("synthetic-reviewer", "claude", "cred-reviewer"),
    )

    def test_foreign_reviewer_cannot_approve_or_request_changes(self):
        for identity in self.FOREIGN:
            for verdict in VERDICTS_UNDER_TEST:
                with self.subTest(identity=identity, verdict=verdict):
                    orch = default_cycle()
                    drive_until(orch, pending_review)
                    orch.inbox.clear()  # hold the configured review back
                    orch.receive(synthetic_review(HEAD1, verdict,
                                                  reviewer=identity, call=7))
                    self.assertEqual(orch.snapshot.state, "BLOCKED")
                    self.assertEqual(orch.notifications, [])
                    self.assertEqual(len(orch.implementer.calls), 1)
                    self.assertIn("review not from the configured reviewer",
                                  details(orch))

    def test_configured_reviewer_still_accepted(self):
        orch = default_cycle()
        drive_until(orch, pending_review)
        orch.inbox.clear()
        orch.receive(synthetic_review(HEAD1, "APPROVED", call=1))
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(len(orch.notifications), 1)

    def test_configured_reviewer_must_still_be_independent(self):
        orch = default_cycle(
            implementer=SyntheticImplementer(IMPLEMENTER_ID, files=FILES),
            reviewer=SyntheticReviewer(Identity("synthetic-implementer",
                                                "codex", "cred-reviewer")))
        orch.start()
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])


class EventIdTests(unittest.TestCase):
    """Finding 2: validate before consuming an id; detect conflicting reuse."""

    def test_rejected_delivery_does_not_consume_pending_review_id(self):
        for name, change in (("wrong pr", {"pr_number": SYNTHETIC_PR_NUMBER + 1}),
                             ("stale head", {"head_sha": "d" * 40})):
            with self.subTest(case=name):
                orch = default_cycle()
                drive_until(orch, pending_review)
                valid = orch.inbox.pop(0)[1]
                orch.receive(replace(valid, **change))  # same event id
                self.assertEqual(events(orch)[-1], "REJECTED_STALE_OR_UNBOUND")
                self.assertEqual(orch.snapshot.state, "REVIEWING")
                orch.receive(valid)
                self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
                self.assertEqual(len(orch.notifications), 1)
                self.assertNotIn("DUPLICATE_IGNORED", events(orch))

    def test_conflicting_reuse_of_accepted_id_blocks(self):
        for change in ({"verdict": "APPROVED"}, {"findings": ("other",)},
                       {"head_sha": "e" * 40}):
            with self.subTest(change=change):
                probe = default_cycle()
                drive_until(probe, pending_review)
                accepted = probe.inbox[0][1]
                drive_until(probe, lambda o: o.snapshot.state == "REVISING")
                probe.inbox.clear()  # hold the fix back
                probe.receive(replace(accepted, **change))
                self.assertEqual(probe.snapshot.state, "BLOCKED")
                self.assertEqual(probe.notifications, [])
                self.assertTrue(any(d.startswith("conflicting reuse")
                                    for d in details(probe)))

    def test_conflict_behind_approval_prevents_notification(self):
        orch = default_cycle()
        drive_until(orch, lambda o: pending_review(o) and o.snapshot.head_sha == HEAD2)
        approval = orch.inbox[0][1]
        orch.receive(replace(approval, verdict="CHANGES_REQUESTED"))
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])
        self.assertNotIn("NOTIFIED", events(orch))

    def test_conflict_after_notification_withdraws_active_notice(self):
        orch = default_cycle()
        orch.start()
        original_notice = orch.notifications[0]
        approval = next(review for review in orch.accepted.values()
                        if review.verdict == "APPROVED")
        orch.receive(replace(approval, verdict="CHANGES_REQUESTED"))
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])
        self.assertEqual(orch.invalidated_notifications, [original_notice])
        self.assertEqual(events(orch)[-1], "READINESS_INVALIDATED")
        orch.receive(approval)
        self.assertEqual(len(orch.invalidated_notifications), 1)
        self.assertEqual(events(orch).count("NOTIFIED"), 1)

    def test_identical_retry_while_review_pending(self):
        orch = default_cycle()
        drive_until(orch, pending_review)
        review = orch.inbox[0][1]
        orch.receive(review)  # inbox now holds the same review twice
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(len(orch.implementer.calls), 2)
        self.assertEqual(orch.reviewer.calls, 2)
        self.assertEqual(len(orch.notifications), 1)
        self.assertEqual(events(orch).count("DUPLICATE_IGNORED"), 1)

    def test_identical_retry_while_fix_pending(self):
        orch = default_cycle()
        drive_until(orch, pending_review)
        review = orch.inbox[0][1]
        drive_until(orch, lambda o: o.snapshot.state == "REVISING")
        orch.inbox.insert(0, ("review", review))  # redelivery before the fix
        orch.run()
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(len(orch.implementer.calls), 2)
        self.assertEqual(len(orch.notifications), 1)
        self.assertIn("DUPLICATE_IGNORED", events(orch))


class _RaisingImplementer(SyntheticImplementer):
    def __init__(self, fail_on_call, result=None, exc=None):
        super().__init__(IMPLEMENTER_ID, files=FILES)
        self.fail_on_call = fail_on_call
        self.result = result
        self.exc = exc

    def implement(self, task_id, findings=()):
        if len(self.calls) + 1 == self.fail_on_call:
            self.calls.append(tuple(findings))
            if self.exc is not None:
                raise self.exc
            return self.result
        return super().implement(task_id, findings)


class _RaisingReviewer(SyntheticReviewer):
    def __init__(self, result=None, exc=None):
        super().__init__(REVIEWER_ID)
        self.result = result
        self.exc = exc

    def review(self, repository, pr_number, head_sha):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


class AdapterFailureTests(unittest.TestCase):
    """Finding 3: adapter failures fail closed to BLOCKED, never notify."""

    def _assert_blocked(self, orch, detail_prefix):
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])
        self.assertTrue(any(str(d).startswith(detail_prefix)
                            for d in details(orch)), details(orch))
        # Terminal: further runs and deliveries change nothing.
        orch.receive(synthetic_review(HEAD1, "APPROVED", call=50))
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])

    def test_implementer_exception_on_first_call(self):
        orch = default_cycle(implementer=_RaisingImplementer(
            1, exc=RuntimeError("synthetic failure text")))
        orch.start()
        self._assert_blocked(orch, "implementer failure: RuntimeError")
        self.assertEqual(orch.reviewer.calls, 0)
        self.assertFalse(any("synthetic failure text" in str(d)
                             for d in details(orch)))

    def test_implementer_exception_during_fix(self):
        orch = default_cycle(implementer=_RaisingImplementer(
            2, exc=OSError("synthetic")))
        orch.start()
        self._assert_blocked(orch, "implementer failure: OSError")
        self.assertEqual(orch.reviewer.calls, 1)

    def test_implementer_missing_or_malformed_result(self):
        for result in (None, "not an implementation",
                       cycle.Implementation("not-a-sha", FILES),
                       cycle.Implementation("A" * 40, FILES),
                       cycle.Implementation(HEAD1, 42)):
            with self.subTest(result=result):
                orch = default_cycle(implementer=_RaisingImplementer(
                    1, result=result))
                orch.start()
                self.assertEqual(orch.snapshot.state, "BLOCKED")
                self.assertEqual(orch.notifications, [])
                self.assertEqual(orch.reviewer.calls, 0)

    def test_reviewer_exception(self):
        orch = default_cycle(reviewer=_RaisingReviewer(
            exc=ValueError("synthetic")))
        orch.start()
        self._assert_blocked(orch, "reviewer failure: ValueError")

    def test_reviewer_missing_result(self):
        for result in (None, {"verdict": "APPROVED"}):
            with self.subTest(result=result):
                orch = default_cycle(reviewer=_RaisingReviewer(result=result))
                orch.start()
                self._assert_blocked(orch, "reviewer returned no valid result")

    def test_empty_verdict_script(self):
        with self.assertRaises(ValueError):
            SyntheticReviewer(REVIEWER_ID, verdicts=())
        with self.assertRaises(ValueError):
            SyntheticReviewer(REVIEWER_ID, verdicts=iter(()))
        reviewer = SyntheticReviewer(REVIEWER_ID)
        reviewer.verdicts = ()  # script emptied after construction
        orch = default_cycle(reviewer=reviewer)
        orch.start()
        self._assert_blocked(orch, "reviewer failure: IndexError")

    def test_malformed_event_fails_closed(self):
        orch = default_cycle()
        drive_until(orch, pending_review)
        orch.inbox.clear()
        orch.receive(replace(synthetic_review(HEAD1, "APPROVED"),
                             event_id=["unhashable"]))
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])
        self.assertIn("reviewer returned no valid result", details(orch))


class ReadinessInvariantTests(unittest.TestCase):
    """READY_FOR_OWNER only under all simulated validated conditions."""

    def test_ready_only_when_every_condition_holds(self):
        for claim, ci_ok, paths_ok, independent in itertools.product(
                (True, False), repeat=4):
            with self.subTest(claim=claim, ci=ci_ok, paths=paths_ok,
                              independent=independent):
                files = FILES if paths_ok else FILES + (".github/x.yml",)
                reviewer_id = (REVIEWER_ID if independent else
                               Identity("synthetic-reviewer", "codex",
                                        "cred-implementer"))
                orch = default_cycle(
                    claim_verified=claim,
                    ci_results={HEAD1: True, HEAD2: ci_ok},
                    implementer=SyntheticImplementer(IMPLEMENTER_ID,
                                                     files=files),
                    reviewer=SyntheticReviewer(reviewer_id))
                orch.start()
                expected = claim and ci_ok and paths_ok and independent
                if expected:
                    self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
                    self.assertEqual(len(orch.notifications), 1)
                else:
                    self.assertEqual(orch.snapshot.state, "BLOCKED")
                    self.assertEqual(orch.notifications, [])

    def test_notify_does_nothing_outside_ready(self):
        orch = default_cycle(claim_verified=False)
        orch.start()
        orch._notify()
        self.assertEqual(orch.notifications, [])


class DeduplicationScopeTests(unittest.TestCase):
    """Finding 4: the guarantee is single-instance and in-memory only."""

    def test_guarantee_is_documented_not_claimed_across_instances(self):
        doc = cycle.Orchestrator.__doc__
        self.assertIn("ONE instance in ONE process", doc)
        self.assertIn("not claimed to be safe", doc)
        reasons = " ".join(activation_status()["reasons"])
        self.assertIn("single-instance", reasons)
        self.assertIn("restart- and concurrency-safe delivery is unverified",
                      reasons)

    def test_fresh_instance_has_no_memory_of_earlier_instance(self):
        # Documents the limitation: each instance notifies once on its own.
        first, second = default_cycle(), default_cycle()
        first.start()
        second.start()
        self.assertEqual(len(first.notifications), 1)
        self.assertEqual(len(second.notifications), 1)
        self.assertEqual(second.accepted.keys(), first.accepted.keys())


@unittest.skipUnless(sys.platform == "linux", "atomic output requires Linux")
class CliOutputSafetyTests(unittest.TestCase):
    """Finding 5: no overwrite, no symlink targets, no partial report pair."""

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cycle.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_existing_directory_refused_and_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report")
            os.mkdir(target)
            keep = os.path.join(target, "cycle.json")
            with open(keep, "w", encoding="utf-8") as handle:
                handle.write("synthetic existing content\n")
            code, out, err = self._main(["--out", target])
            self.assertEqual(code, 2)
            self.assertIn("already exists", err)
            self.assertEqual(out, "")
            with open(keep, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "synthetic existing content\n")
            self.assertEqual(os.listdir(target), ["cycle.json"])

    def test_existing_file_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("x")
            code, _, err = self._main(["--out", target])
            self.assertEqual(code, 2)
            with open(target, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "x")

    def test_symlink_target_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "real")
            os.mkdir(real)
            link = os.path.join(tmp, "link")
            os.symlink(real, link)
            dangling = os.path.join(tmp, "dangling")
            os.symlink(os.path.join(tmp, "missing"), dangling)
            for target in (link, dangling):
                with self.subTest(target=os.path.basename(target)):
                    code, _, err = self._main(["--out", target])
                    self.assertEqual(code, 2)
                    self.assertIn("already exists", err)
            self.assertEqual(os.listdir(real), [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "missing")))

    def test_destination_inside_repository_refused(self):
        target = os.path.join(cycle._repository_root(),
                              "synthetic-cycle-output-test")
        self.assertFalse(os.path.lexists(target))
        code, _, err = self._main(["--out", target])
        self.assertEqual(code, 2)
        self.assertIn("outside the repository", err)
        self.assertFalse(os.path.lexists(target))

    def test_missing_parent_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self._main(
                ["--out", os.path.join(tmp, "missing", "report")])
            self.assertEqual(code, 2)
            self.assertIn("parent directory", err)

    def test_second_write_failure_leaves_nothing(self):
        real_open = os.open
        calls = []

        def failing_open(path, flags, mode=0o777, **kw):
            if path in ("cycle.json", "notifications.jsonl"):
                calls.append(path)
            if path == "notifications.jsonl":
                raise OSError("synthetic second-write failure")
            return real_open(path, flags, mode, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report")
            with mock.patch("orchestrator.cycle.os.open", failing_open):
                code, out, err = self._main(["--out", target])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("OSError", err)
            # The second exclusive create (notifications.jsonl) failed;
            # later os.open calls come from removing the staging directory.
            self.assertTrue(calls[0].endswith("cycle.json"))
            self.assertTrue(calls[1].endswith("notifications.jsonl"))
            self.assertFalse(os.path.lexists(target))
            self.assertEqual(os.listdir(tmp), [])  # staging dir removed

    def test_write_outputs_raises_without_partial_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report")
            with mock.patch.object(cycle, "_no_replace_rename",
                                   return_value=mock.Mock(side_effect=OSError("synthetic"))):
                with self.assertRaises(OSError):
                    cycle.write_outputs(target, [("a", "1"), ("b", "2")])
            self.assertEqual(os.listdir(tmp), [])


class StrictFixtureTests(unittest.TestCase):
    def test_claim_must_be_exactly_true(self):
        for value in (None, False, 1, "false"):
            with self.subTest(value=value):
                orch = default_cycle(claim_verified=value)
                orch.start()
                self.assertEqual(orch.snapshot.state, "BLOCKED")
                self.assertEqual(orch.implementer.calls, [])

    def test_malformed_review_does_not_consume_event_id(self):
        for change in ({"event_id": None}, {"event_id": ""}, {"event_id": "z" * 40},
                       {"pr_number": float(SYNTHETIC_PR_NUMBER)}, {"head_sha": None},
                       {"findings": ["not a tuple"]}, {"verdict": "UNKNOWN"}):
            with self.subTest(change=change):
                orch = default_cycle()
                drive_until(orch, pending_review)
                pending = orch.inbox.pop(0)[1]
                orch.receive(replace(pending, **change))
                self.assertEqual(orch.snapshot.state, "BLOCKED")
                self.assertEqual(orch.accepted, {})
                self.assertEqual(orch.notifications, [])


@unittest.skipUnless(sys.platform == "linux", "atomic output requires Linux")
class OutputRaceTests(unittest.TestCase):
    def test_empty_destination_created_at_publication_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report")
            publish = cycle._no_replace_rename()

            def create_then_publish(fd, staging, name):
                os.mkdir(name, dir_fd=fd)
                publish(fd, staging, name)

            with mock.patch.object(cycle, "_no_replace_rename", return_value=create_then_publish):
                with self.assertRaises(FileExistsError):
                    cycle.write_outputs(target, [("cycle.json", "{}")])
            self.assertEqual(os.listdir(tmp), ["report"])
            self.assertEqual(os.listdir(target), [])

    def test_ancestor_replaced_during_write_cannot_redirect_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, moved, alternate = (os.path.join(tmp, name)
                                        for name in ("parent", "moved", "alternate"))
            os.mkdir(parent)
            os.mkdir(alternate)
            real_open = os.open

            def swap_on_write(path, flags, *args, **kwargs):
                if path == "cycle.json":
                    os.rename(parent, moved)
                    os.symlink(alternate, parent)
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(cycle.os, "open", side_effect=swap_on_write):
                with self.assertRaises(OSError):
                    cycle.write_outputs(os.path.join(parent, "report"),
                                        [("cycle.json", "{}")])
            self.assertEqual(os.listdir(alternate), [])
            self.assertEqual(os.listdir(moved), [])

    def test_existing_symlink_ancestor_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "link")
            os.symlink(tmp, link)
            with self.assertRaises(OSError):
                cycle.write_outputs(os.path.join(link, "report"),
                                    [("cycle.json", "{}")])
            self.assertEqual(os.listdir(tmp), ["link"])



class FailClosedBoundaryTests(unittest.TestCase):
    """Malformed synthetic fixtures and boundary errors end in BLOCKED."""

    def _assert_blocked(self, orch):
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])
        self.assertIn("BLOCK", events(orch))

    def test_malformed_fixture_fields_block_without_escaping(self):
        for name, overrides in (("repository=123", {"repository": 123}),
                                ("repository=None", {"repository": None}),
                                ("ci_results=[]", {"ci_results": []}),
                                ("ci_results='x'", {"ci_results": "x"})):
            with self.subTest(fixture=name):
                orch = default_cycle(**overrides)
                orch.start()  # must not raise
                self._assert_blocked(orch)
                self.assertIn("invalid cycle fixture", details(orch))
                self.assertEqual(orch.implementer.calls, [])
                self.assertEqual(orch.reviewer.calls, 0)

    def test_block_does_not_depend_on_transition(self):
        with mock.patch("orchestrator.cycle.transition",
                        side_effect=RuntimeError("synthetic")):
            orch = default_cycle()
            orch.start()
        self._assert_blocked(orch)
        self.assertIn("coordinator error: RuntimeError", details(orch))
        self.assertEqual(orch.implementer.calls, [])

    def test_block_works_with_malformed_snapshot_fields(self):
        orch = default_cycle(repository=123, ci_results=[])
        orch._block("synthetic direct block")
        self._assert_blocked(orch)
        entry = orch.transcript[-1]
        self.assertEqual((entry["event"], entry["actor"], entry["detail"]),
                         ("BLOCK", "coordinator", "synthetic direct block"))

    def test_boundary_exception_after_readiness_withdraws_notice(self):
        orch = default_cycle()
        orch.start()
        notice = orch.notifications[0]
        orch.inbox.append(("unknown_event_kind", None))
        orch.run()
        self._assert_blocked(orch)
        self.assertEqual(orch.invalidated_notifications, [notice])
        self.assertEqual(events(orch)[-2:], ["BLOCK", "READINESS_INVALIDATED"])
        self.assertIn("coordinator error: AttributeError", details(orch))
        # Audit history is kept and nothing is re-notified afterwards.
        self.assertEqual(events(orch).count("NOTIFIED"), 1)
        orch.run()
        self.assertEqual(orch.notifications, [])



class StageTwoPathEvidenceTests(unittest.TestCase):
    """S2-1: the coordinator never reports path verification it has not done."""

    def _spy(self):
        calls = []
        real = cycle.transition

        def spy(snapshot, event, **kw):
            calls.append((event, kw["head_sha"], kw["allowed_paths"]))
            return real(snapshot, event, **kw)
        return calls, spy

    def test_claim_reports_no_path_verification(self):
        calls, spy = self._spy()
        with mock.patch("orchestrator.cycle.transition", spy):
            orch = default_cycle()
            orch.start()
        self.assertEqual(orch.snapshot.state, "READY_FOR_OWNER")
        self.assertEqual(calls[0][0], "CLAIM_ACCEPTED")
        self.assertIs(calls[0][2], False)
        for event, head, allowed in calls[1:]:
            with self.subTest(event=event, head=head[:12]):
                self.assertIs(allowed, True)
                self.assertIs(orch.paths_verified.get(head), True)

    def test_missing_path_evidence_blocks_review(self):
        orch = default_cycle()
        drive_until(orch, pending_review)
        orch.paths_verified.pop(HEAD1)
        orch.run()
        self.assertEqual(orch.snapshot.state, "BLOCKED")
        self.assertEqual(orch.notifications, [])

    def test_non_true_path_evidence_blocks_review(self):
        for value in (False, None, 1, "yes"):
            with self.subTest(value=repr(value)):
                orch = default_cycle()
                drive_until(orch, pending_review)
                orch.paths_verified[HEAD1] = value
                orch.run()
                self.assertEqual(orch.snapshot.state, "BLOCKED")
                self.assertEqual(orch.notifications, [])


if __name__ == "__main__":
    unittest.main()
