"""Synthetic-only tests for the T-003 fail-closed orchestration planner."""
import inspect
import unittest

from orchestrator.state import Snapshot, transition

REPO = "cooljudge72-lgtm/Orchestrator-public-test"
A = "a" * 40
B = "b" * 40
C = "c" * 40


def step(s, event, head=None, actor="claude", **kw):
    # Positive paths state the allowed-path verification explicitly; the
    # planner no longer assumes it (Codex review of PR #10, finding 2).
    kw.setdefault("allowed_paths", True)
    return transition(s, event, repository=REPO, head_sha=head or s.head_sha,
                      actor=actor, claim_verified=True, **kw)


class StateTests(unittest.TestCase):
    def test_happy_path_never_merges(self):
        s = Snapshot(REPO, "T-003", A, "CLAIMED")
        s = step(s, "CLAIM_ACCEPTED", actor="owner")
        self.assertEqual(s.state, "IMPLEMENTING")
        s = step(s, "IMPLEMENTED", B)
        self.assertEqual(s.state, "REVIEWING")
        s = step(s, "REVIEW_APPROVED", actor="codex",
                 reviewer_independent=True, ci_passed=True)
        self.assertEqual(s.state, "READY_FOR_OWNER")
        self.assertEqual(step(s, "MERGE", actor="owner").state, "BLOCKED")

    def test_revision_cap(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        for i, head in enumerate((B, C)):
            s = step(s, "REVIEW_CHANGES", actor="codex",
                     reviewer_independent=True)
            self.assertEqual(s.revision_rounds, i + 1)
            s = step(s, "IMPLEMENTED", head)
        self.assertEqual(step(s, "REVIEW_CHANGES", actor="codex",
                              reviewer_independent=True).state, "BLOCKED")

    def test_stale_head_and_self_review_blocked(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(step(s, "REVIEW_APPROVED", B, actor="codex",
                              reviewer_independent=True, ci_passed=True).state, "BLOCKED")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="claude",
                              reviewer_independent=True, ci_passed=True).state, "BLOCKED")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="codex",
                              ci_passed=True).state, "BLOCKED")

    def test_unverified_claim_or_paths_or_repo_blocks(self):
        s = Snapshot(REPO, "T-003", A, "CLAIMED")
        self.assertEqual(transition(s, "CLAIM_ACCEPTED", repository=REPO,
                         head_sha=A, actor="owner").state, "BLOCKED")
        self.assertEqual(step(s, "CLAIM_ACCEPTED", actor="owner",
                              allowed_paths=False).state, "BLOCKED")
        self.assertEqual(transition(s, "CLAIM_ACCEPTED", repository="other/repo",
                         head_sha=A, actor="owner", claim_verified=True).state, "BLOCKED")

    def test_no_approval_without_ci(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(step(s, "REVIEW_APPROVED", actor="codex",
                              reviewer_independent=True).state, "BLOCKED")

    def test_same_head_implementation_rejected(self):
        s = Snapshot(REPO, "T-003", A, "IMPLEMENTING")
        self.assertEqual(step(s, "IMPLEMENTED").state, "BLOCKED")

    def test_blocked_is_terminal(self):
        s = Snapshot(REPO, "T-003", A, "BLOCKED")
        self.assertEqual(step(s, "CLAIM_ACCEPTED", actor="owner").state, "BLOCKED")



GATES = ("allowed_paths", "claim_verified", "ci_passed", "reviewer_independent")
# Values that are not exactly True: missing-like, false, malformed, truthy.
NOT_TRUE = (False, None, 0, 1, 1.0, "yes", "True", "", ["ok"], {"ok": True},
            object())


def gated(event):
    """(starting snapshot, actor, new head, gates the event depends on)."""
    return {
        "CLAIM_ACCEPTED": (Snapshot(REPO, "T-003", A, "CLAIMED"), "owner", A,
                           ("allowed_paths", "claim_verified")),
        "IMPLEMENTED": (Snapshot(REPO, "T-003", A, "IMPLEMENTING"), "claude", B,
                        ("allowed_paths", "claim_verified")),
        "REVIEW_CHANGES": (Snapshot(REPO, "T-003", A, "REVIEWING"), "codex", A,
                           ("allowed_paths", "claim_verified",
                            "reviewer_independent")),
        "REVIEW_APPROVED": (Snapshot(REPO, "T-003", A, "REVIEWING"), "codex", A,
                            GATES),
    }[event]


EXPECTED = {"CLAIM_ACCEPTED": "IMPLEMENTING", "IMPLEMENTED": "REVIEWING",
            "REVIEW_CHANGES": "REVISING", "REVIEW_APPROVED": "READY_FOR_OWNER"}


def call(event, **gates):
    snapshot, actor, head, _ = gated(event)
    return transition(snapshot, event, repository=REPO, head_sha=head,
                      actor=actor, **gates).state


class GateStrictnessTests(unittest.TestCase):
    """Every verification gate defaults to False and passes only for True."""

    def test_all_gates_default_to_false(self):
        params = inspect.signature(transition).parameters
        for gate in GATES:
            with self.subTest(gate=gate):
                self.assertIs(params[gate].default, False)

    def test_exact_true_gates_allow_each_event(self):
        for event, expected in EXPECTED.items():
            with self.subTest(event=event):
                self.assertEqual(call(event, **dict.fromkeys(GATES, True)),
                                 expected)

    def test_omitted_gate_blocks(self):
        for event in EXPECTED:
            for gate in gated(event)[3]:
                with self.subTest(event=event, omitted=gate):
                    gates = {g: True for g in GATES if g != gate}
                    self.assertEqual(call(event, **gates), "BLOCKED")

    def test_not_exactly_true_gate_blocks(self):
        for event in EXPECTED:
            for gate in gated(event)[3]:
                for value in NOT_TRUE:
                    with self.subTest(event=event, gate=gate, value=repr(value)):
                        gates = dict.fromkeys(GATES, True)
                        gates[gate] = value
                        self.assertEqual(call(event, **gates), "BLOCKED")

    def test_malformed_unrelated_gate_still_blocks(self):
        # A non-boolean gate value is a malformed verification result even on
        # an event that does not otherwise depend on that gate.
        for event in ("CLAIM_ACCEPTED", "IMPLEMENTED"):
            for gate in ("ci_passed", "reviewer_independent"):
                for value in (None, 1, "yes", ["ok"]):
                    with self.subTest(event=event, gate=gate, value=repr(value)):
                        gates = dict.fromkeys(GATES, True)
                        gates[gate] = value
                        self.assertEqual(call(event, **gates), "BLOCKED")

    def test_missing_path_verification_never_reaches_ready(self):
        # Codex finding 2: matching SHA, verified claim, independent review and
        # passing CI must not reach READY_FOR_OWNER without path verification.
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        for paths in ("omitted", False, None, "yes", 1):
            with self.subTest(allowed_paths=repr(paths)):
                kw = dict(repository=REPO, head_sha=A, actor="codex",
                          ci_passed=True, reviewer_independent=True,
                          claim_verified=True)
                if paths != "omitted":
                    kw["allowed_paths"] = paths
                result = transition(s, "REVIEW_APPROVED", **kw)
                self.assertEqual(result.state, "BLOCKED")
                self.assertNotEqual(result.state, "READY_FOR_OWNER")



def review_changes(snapshot, **kw):
    kw.setdefault("repository", REPO)
    return transition(snapshot, "REVIEW_CHANGES", head_sha=A, actor="codex",
                      **dict.fromkeys(GATES, True), **kw)


class RepositoryIdentityTests(unittest.TestCase):
    """Codex P2: exact public repository identity; malformed never raises."""

    BAD = (None, 123, b"cooljudge72-lgtm/Orchestrator-public-test", ["x"],
           "evil/Orchestrator-public-test",
           "cooljudge72-lgtm/x/Orchestrator-public-test",
           "CoolJudge72-lgtm/orchestrator-public-test",
           "cooljudge72-lgtm/Orchestrator-public-test/",
           " cooljudge72-lgtm/Orchestrator-public-test", "")

    def test_exact_repository_still_allowed(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(review_changes(s).state, "REVISING")

    def test_malformed_or_lookalike_repository_blocks_without_raising(self):
        for value in self.BAD:
            with self.subTest(value=repr(value)):
                # Same bad value in call and snapshot: equality alone must not pass.
                s = Snapshot(value, "T-003", A, "REVIEWING")
                self.assertEqual(review_changes(s, repository=value).state, "BLOCKED")
                # Bad call value against the genuine snapshot.
                good = Snapshot(REPO, "T-003", A, "REVIEWING")
                self.assertEqual(review_changes(good, repository=value).state, "BLOCKED")

    def test_str_subclass_repository_blocks(self):
        class Lookalike(str):
            pass
        value = Lookalike(REPO)
        s = Snapshot(value, "T-003", A, "REVIEWING")
        self.assertEqual(review_changes(s, repository=value).state, "BLOCKED")

    def test_omitted_repository_blocks_without_raising(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        result = transition(s, "REVIEW_CHANGES", head_sha=A, actor="codex",
                            **dict.fromkeys(GATES, True))
        self.assertEqual(result.state, "BLOCKED")


class RevisionRoundsTypeTests(unittest.TestCase):
    """Codex P2: revision_rounds must be an int (not bool) in 0..MAX_ROUNDS."""

    def test_valid_rounds_unchanged(self):
        for rounds, expected in ((0, "REVISING"), (1, "REVISING"), (2, "BLOCKED")):
            with self.subTest(rounds=rounds):
                s = Snapshot(REPO, "T-003", A, "REVIEWING", rounds)
                self.assertEqual(review_changes(s).state, expected)

    def test_invalid_rounds_block_without_raising(self):
        for rounds in (float("nan"), float("inf"), True, False, 1.0, 0.0, "1",
                       None, -1, 3, [1]):
            with self.subTest(rounds=repr(rounds)):
                s = Snapshot(REPO, "T-003", A, "REVIEWING", rounds)
                self.assertEqual(review_changes(s).state, "BLOCKED")



class SnapshotStateTypeTests(unittest.TestCase):
    """snapshot.state is type-checked before the STATES membership test."""

    def test_malformed_state_blocks_without_raising(self):
        for state in (["REVIEWING"], {"REVIEWING": 1}, {"REVIEWING"}, None, 1,
                      b"REVIEWING", "reviewing", "UNKNOWN", ""):
            with self.subTest(state=repr(state)):
                s = Snapshot(REPO, "T-003", A, state)
                for event in ("REVIEW_CHANGES", "REVIEW_APPROVED", "BLOCK"):
                    result = transition(s, event, repository=REPO, head_sha=A,
                                        actor="codex", **dict.fromkeys(GATES, True))
                    self.assertEqual(result.state, "BLOCKED")

    def test_str_subclass_state_blocks(self):
        class Lookalike(str):
            pass
        s = Snapshot(REPO, "T-003", A, Lookalike("REVIEWING"))
        self.assertEqual(review_changes(s).state, "BLOCKED")

    def test_valid_states_unchanged(self):
        s = Snapshot(REPO, "T-003", A, "REVIEWING")
        self.assertEqual(review_changes(s).state, "REVISING")


if __name__ == "__main__":
    unittest.main()
