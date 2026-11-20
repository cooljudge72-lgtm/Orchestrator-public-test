# Lock test: what it does and the remaining risk

## What it does

`verify-lock.yml` starts 10 threads that create the same ref,
`refs/lockcheck/verify-<run id>-<time>`, pointing at the commit being tested. It passes only if
exactly one create succeeds, the other nine get `422 Reference already exists`, the ref points at
that commit, the ref is deleted afterwards (cleanup always runs), and a read-back finds nothing
left. Any error, including a cleanup failure, is a FAIL. It creates no tags or other objects.

## Who can start it

`workflow_dispatch` can only be started by people with write access to the repository. The job
also requires `github.actor == github.repository_owner` and `github.ref == refs/heads/main`.

## Remaining risk of `contents: write`

For the job's lifetime, the `GITHUB_TOKEN` with `contents: write` could also push branches, create
or delete tags and releases, and change any ref in this repository. Our code only touches
`refs/lockcheck/`, but **that limit is enforced by our code, not by GitHub**. The token is scoped
to this repository only and expires when the job ends; `persist-credentials: false` keeps it out
of the checkout. GitHub's ruleset on `main` (no direct pushes, no deletion, no force push) blocks
the most damaging misuse independently of our code. Third-party actions are pinned to full
commit SHAs.
