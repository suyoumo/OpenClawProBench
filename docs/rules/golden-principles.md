# Golden Principles

- Prefer deterministic scoring and explicit metadata over clever but opaque summaries.
- Optimize for user self-evaluation: if a partial run can be misread, expose the missing context directly in the report.
- Preserve evidence first, clean up second.
- Reuse expensive prior work through current-format report deserialization and resume flows before rerunning live scenarios.
- Keep the CLI thin and the harness modules composable.
- Make small changes that line up docs, tests, and runtime behavior in one pass.
