# Phase 2 pilot: assisted Claude–Codex collaboration

This pilot is **assisted, not autonomous**. No GitHub App, secret or paid API is used, so neither
agent runs inside GitHub Actions. GitHub enforces the lock, pull requests, the required `unittest`
check and branch protection; the agents act through access that already exists, on the owner's
explicit instruction; deterministic code judges the result. **Nothing merges automatically.**

## Roles

| Role | Who | Can |
|---|---|---|
| Owner | repository owner | claim tasks, relay verdicts, run the status check, merge |
| Implementer | Claude (interactive session, on instruction) | work on `pilot/<TASK_ID>` after a verified claim, open a PR |
| Reviewer | Codex (via the owner's Codex session) | review the PR diff; the owner posts its verdict verbatim |
| Status | `pilot-status` workflow (read-only) | report a verdict; cannot write, comment or merge |

## Procedure (each step needs owner approval)

1. Owner runs **claim-task** with `task_id` and `agent`. Expected `CLAIM T-001: ACQUIRED`. A second
   run for the same task reports `HELD` and fails, by design.
2. Claude confirms the claim exists, creates `pilot/<TASK_ID>` from `main`, changes only the files
   in `tasks/<TASK_ID>.json` → `allowed_paths`, runs the tests and opens a PR into `main`.
3. `unittest` runs on the PR (required by the ruleset).
4. Codex reviews the diff. The owner posts one new comment whose **first line** is exactly
   `CODEX-REVIEW <TASK_ID> <40-character head SHA> APPROVED` or `... CHANGES_REQUESTED`,
   followed by the findings. Do not edit verdict comments; post a new one instead.
5. On `CHANGES_REQUESTED`, Claude revises (at most `max_revision_rounds`, default 2). Every new
   commit voids earlier verdicts; a new verdict for the new head SHA is required.
6. Owner runs **pilot-status** with the PR number and reads the run summary.
7. On `READY_FOR_OWNER` the owner decides whether to merge. Nothing merges automatically.

## What `pilot-status` requires for READY_FOR_OWNER (fail closed)

All facts are collected for one PR snapshot; the PR is read again at the end and any change to its
head, base, state or counts gives `BLOCKED` (run the status again).

- **PR:** open, `merged` explicitly false, same repository, `pilot/<TASK_ID>` → `main`; the task
  definition is read from **main**, never from the PR.
- **Ruleset (read-only check):** `main` still has `pull_request`, `required_status_checks` with
  `unittest` from GitHub Actions (integration 15368), `non_fast_forward` and `deletion`.
- **Claim provenance:** `refs/lockcheck/task-<TASK_ID>` points at the annotated tag `claim-<TASK_ID>`;
  the tag targets exactly the commit recorded in its identity; that identity names run R; the
  Actions API shows R is the owner's (actor and triggering actor) manual `claim-task` run on `main`,
  **attempt 1**, with head SHA equal to the recorded SHA and run title `claim-task <TASK_ID>`,
  concluded `success`. `claim.py` exits 0 **only** when it created the claim, so a successful run
  titled for this task is the evidence that it acquired this claim. R must have finished
  (`updated_at`) before the PR was opened; run *creation* time is not used as proof.
- **Files:** the file list is complete (count equals the PR's `changed_files`), every path and every
  rename **source** is in `allowed_paths`, and only plain statuses are accepted (`copied` is refused).
- **Trusted CI:** `.github/workflows/tests.yml` is identical on `main` and on the head commit; the
  newest `tests.yml` `pull_request` run for the head commit is on the PR branch, in this repository,
  and associated with this PR; the jobs of its **current attempt** contain exactly one `unittest`
  job, on the head commit, whose check run (same id, from the GitHub Actions app 15368) succeeded.
  A check name and app alone are not trusted.
- **Verdict:** among owner-authored comments whose first line starts with `CODEX-REVIEW`, only the
  **newest** is considered. It must be valid: exact first line
  `CODEX-REVIEW <TASK_ID> <40-hex head SHA> APPROVED`, unedited, naming the **current** head.
  If the newest owner verdict is invalid, the status is `NEEDS_REVIEW`; an older approval is never
  restored. Revision rounds may not exceed `max_revision_rounds`.
- **Completeness:** files, comments, check runs, workflow runs and jobs are read through GitHub's
  `Link` pagination; counts must match `changed_files`, `comments` or `total_count`. Anything
  incomplete, missing or erroring gives `BLOCKED`.

## Manual merge procedure (owner, SHA-checked)

1. Run **pilot-status** for the PR and note the head SHA `X` in a `READY_FOR_OWNER` result.
2. Merge only if the PR's head is still `X`. Preferred, from your own machine:
   `gh pr merge <PR> --merge --match-head-commit X` (GitHub refuses the merge if the head moved).
   In the web UI, first confirm the latest commit shown on the PR is `X`.
3. If the head changed, do not merge: wait for tests, a new verdict for the new head and a new
   `READY_FOR_OWNER`.

## Enforced by GitHub vs. procedural

| Control | Enforced by |
|---|---|
| No direct push, force push or deletion on `main`; PR and `unittest` (GitHub Actions) required | GitHub ruleset |
| Job permissions (`contents: write` only in `claim-task` and `verify-lock`; read-only elsewhere) | GitHub Actions |
| Manual workflows run only for the owner on `main` | workflow `if:` conditions |
| One claim per task | GitHub create-reference (verified atomic) |
| Codex really reviewed; verdict relayed verbatim; merge only after `READY_FOR_OWNER` and SHA check | **Procedure (owner)** |
| Claude starts only after a claim and changes only allowed files | **Procedure**, checked afterwards by `pilot-status` |

## Known limitations of this pilot

- **Permanent claims.** Claims are never deleted by automation. A claimed task stays claimed even if
  the work is abandoned; use a new task id (e.g. `T-002`) to retry. Only the owner can remove a
  claim manually (`git push origin :refs/lockcheck/task-T-001` from their own machine), which should
  be recorded and is outside this pilot's procedure.
- **Unreferenced tag objects.** Each claim attempt creates a tag object first; a losing attempt
  leaves it unreferenced (metadata only) until GitHub garbage-collects it.
- **`contents: write` is broad.** In `claim-task` and `verify-lock` the job token could also push to
  unprotected branches, create or delete tags and other refs, and update any branch the ruleset does
  not protect (including fast-forward updates). It is **not** incapable of changing branches; only
  the ruleset keeps it from changing `main`. The `refs/lockcheck/` limit is enforced by our code.
- **Merge-commit semantics.** `pull_request` runs test GitHub's merge of the head into the base *as
  it was when the run started*. If `main` moves later, the tested merge may differ from the final
  merge; the ruleset does not require branches to be up to date. Re-run the tests (or update the
  branch) before merging if `main` changed. This cannot be fully verified from the API.
- **Edit and delete metadata.** An edited verdict is detected only by `updated_at` differing from
  `created_at` (treated as invalid even if the edit was harmless). GitHub's REST API exposes no edit
  history, and a **deleted** comment simply disappears: deleting a newer verdict would make an older
  one the newest again. Only the owner can delete owner comments; do not delete verdicts.
- **Claim publication time** is bounded by the claim run's `updated_at`; if GitHub updates that field
  after completion, the check fails closed.
- **Ruleset bypass list** is not visible to the read-only status job; it was verified manually as
  empty and must not be changed.
- **Review identity.** The verdict is tied to the owner's account and the exact head SHA, not
  cryptographically to Codex.
- The claim proves exclusivity per task, not which agent instance performed the work.
