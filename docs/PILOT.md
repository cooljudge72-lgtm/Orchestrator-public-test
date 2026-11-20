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

- PR open, same repository, `pilot/<TASK_ID>` → `main`; task definition read from **main**.
- Claim `refs/lockcheck/task-<TASK_ID>` exists and its tag records the run identity; the Actions
  API confirms that run was the owner's successful manual `claim-task` run on `main`, not re-run,
  and created before the PR.
- Changed files are all within `allowed_paths`.
- The latest `unittest` check from GitHub Actions on the head commit succeeded.
- The latest owner-authored, unedited `CODEX-REVIEW` verdict names the **current head SHA** and is
  `APPROVED`; revision rounds do not exceed the limit.
Any missing data or API error gives `BLOCKED`.

## Known limitations of this pilot

- **Permanent claims.** Claims are never deleted by automation. A claimed task stays claimed even if
  the work is abandoned; use a new task id (e.g. `T-002`) to retry. Only the owner can remove a
  claim manually (`git push origin :refs/lockcheck/task-T-001` from their own machine), which should
  be recorded and is outside this pilot's procedure.
- **Unreferenced tag objects.** Each claim attempt creates a tag object first; a losing attempt
  leaves it unreferenced (metadata only) until GitHub garbage-collects it.
- **Review identity.** The verdict is tied to the owner's account and the exact head SHA, not
  cryptographically to Codex. Independence relies on the owner relaying Codex's verdict verbatim.
- **`contents: write`** in `claim-task` (and `verify-lock`) is broad; the `refs/lockcheck/` limit is
  enforced by our code, not by GitHub. Both run only manually, by the owner, on `main`.
- The claim proves exclusivity per task, not which agent instance performed the work.
