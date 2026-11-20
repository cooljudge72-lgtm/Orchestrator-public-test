# Review guidelines (Codex, independent reviewer)

## Review guidelines

- Review only the pull request diff on its current head commit, against `tasks/<TASK_ID>.md`.
- Check correctness, edge cases from the acceptance criteria, and test coverage.
- Treat any change outside the task's `allowed_paths`, any dependency, secret or non-synthetic data
  as blocking.
- End with one clear verdict, APPROVED or CHANGES_REQUESTED, and specific findings
  (file, line, problem, fix). The owner posts it as
  `CODEX-REVIEW <TASK_ID> <head SHA> <VERDICT>`.
