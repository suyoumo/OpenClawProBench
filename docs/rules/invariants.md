# Invariants

## Invariant 1: Scenario Identity Is Stable

Scenario IDs are the durable keys used by reports, resume logic, and comparisons. Renaming a scenario requires an explicit migration plan for replay traces, report reuse, and any downstream analysis.

## Invariant 2: Report Schema Changes Must Be End-To-End

If `BenchmarkResult`, `ScenarioResult`, or `TrialResult` gains a new field, update serialization, `from_dict()` deserialization, reporter output, and regression tests in the same change. Resume support only needs to guarantee reuse for reports produced by the current code line; historical report compatibility is not a project goal.

## Invariant 3: Coverage Must Travel With Partial Scores

For subset runs, `overall_score` alone is not interpretable. Any change that touches reporting or comparisons must preserve `coverage`, `covered_weight`, and `normalized_score_on_covered` together.

## Invariant 4: Live Cleanup Happens After Scoring

Live agents and their workspaces are evidence. Do not delete the agent, workspace, transcript, or output artifacts before transcript capture, scoring, and report writing finish. Optional cleanup belongs at the end of the flow, behind explicit user intent such as `--cleanup-agents`.

## Invariant 5: Deterministic Paths Stay Deterministic

Replay mode, loader behavior, and rule-based scoring should remain deterministic. If a task needs custom logic, put it in `custom_checks/` and keep the runner generic.

## Invariant 6: Validation Must Match The Surface Changed

- Reporting or model-schema changes require unit tests plus at least one CLI smoke.
- Scenario or scoring changes require `run.py dry` plus the relevant tests.
- Live-harness changes require a replay safety net and a targeted live smoke when the environment is available.

## Promotion Rules

Promotion is mandatory when the same issue appears more than once.

- Repeated interpretation mistakes become clearer report fields or validation docs.
- Repeated cleanup mistakes become workflow docs or automation.
- Repeated schema regressions become serialization or CLI regression tests.
- Repeated plan churn becomes an active plan or debt-log entry.
