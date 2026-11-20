# orchestrator-public-test

A small public test repository with exactly two purposes:

1. Run Python 3.12 unit tests on GitHub Actions.
2. Run **one manually started** check that GitHub's "create a reference" API behaves as an atomic
   create-if-absent lock (10 concurrent creates of the same ref must yield exactly one success).

It contains only freshly written, standard-library Python, synthetic test doubles, and two
workflows. There is no agent automation here and no secrets are used.

| Path | Purpose |
|---|---|
| `lockcheck/lock.py` | Create-only ref lock (`refs/lockcheck/...`) |
| `lockcheck/verify.py` | The concurrency check, with guaranteed cleanup and strict PASS rules |
| `tests/` | Unit tests with an in-memory API stand-in (no network) |
| `.github/workflows/tests.yml` | Unit tests, read-only permissions |
| `.github/workflows/verify-lock.yml` | Manual lock check; the only job with `contents: write`. **Not present yet**: added later through a reviewed pull request |
| `docs/LOCK_TEST.md` | What the lock check does and its remaining risk |

Run the tests locally:

```bash
python3 -m unittest discover -s tests -t . -v
```
