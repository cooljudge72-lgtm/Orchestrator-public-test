# orchestrator-public-test

A small public test repository. Purposes:

1. Run Python 3.12 unit tests on GitHub Actions.
2. Run **one manually started** check that GitHub's "create a reference" API behaves as an atomic
   create-if-absent lock (10 concurrent creates of the same ref must yield exactly one success).
   Done: verified (1 acquired, 9 held, cleaned up).
3. Phase 2 pilot: an **assisted** Claude–Codex workflow on one synthetic task (`docs/PILOT.md`).

It contains only freshly written, standard-library Python, synthetic test doubles, and two
workflows. There is no agent automation here, no secrets, and nothing merges automatically.

| Path | Purpose |
|---|---|
| `lockcheck/lock.py` | Create-only ref lock (`refs/lockcheck/...`) |
| `lockcheck/verify.py` | The concurrency check, with guaranteed cleanup and strict PASS rules |
| `tests/` | Unit tests with an in-memory API stand-in (no network) |
| `.github/workflows/tests.yml` | Unit tests, read-only permissions |
| `.github/workflows/verify-lock.yml` | Manual lock check (`contents: write`, owner on `main` only) |
| `docs/LOCK_TEST.md` | What the lock check does and its remaining risk |
| `lockcheck/claim.py` | Atomic, identity-carrying task claims (`refs/lockcheck/task-<id>`) |
| `lockcheck/pilot_status.py` | Read-only, fail-closed status of a pilot PR |
| `.github/workflows/claim-task.yml` | Manual task claim (`contents: write`, owner on `main` only) |
| `.github/workflows/pilot-status.yml` | Manual, read-only status report |
| `tasks/T-001.*` | The synthetic pilot task and its allowed files |
| `docs/PILOT.md`, `CLAUDE.md`, `AGENTS.md` | Procedure, limitations, and rules for each agent |

Run the tests locally:

```bash
python3 -m unittest discover -s tests -t . -v
```
