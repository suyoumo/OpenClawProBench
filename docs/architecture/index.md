# Architecture Index

## Mission

OpenClawProBench is a live-first benchmark harness for evaluating model capability inside the OpenClaw runtime. It keeps the benchmark content declarative in `scenarios/`, the grading logic deterministic in `custom_checks/` and `harness/`, and the generated report surface machine-readable in `results/`.

## Current Shape

- `run.py` is the CLI entrypoint for `inventory`, `dry`, `run`, and `compare`.
- `harness/` contains scenario loading, execution, scoring, reporting, and the live OpenClaw bridge.
- `scenarios/` defines benchmark tasks in YAML.
- `datasets/` stores seeded workspace data plus optional setup and teardown scripts.
- `custom_checks/` contains scenario-specific grading logic when YAML checks are not enough.
- `fixtures/` contains deterministic assets used by tests and replay-style regression coverage.
- `tests/` covers loader, scoring, runner, and reporter behavior.
- `results/` is generated output written at runtime and normally kept out of version control.

## Execution Flow

1. `run.py` resolves the requested benchmark profile, filters, and execution options.
2. `harness.loader` loads YAML scenarios, seeded assets, benchmark metadata, and optional scripts.
3. `harness.runner` prepares per-trial workspaces, executes live or replay-backed trials, captures traces, and aggregates scenario metrics.
4. `harness.scoring`, `harness.process_scorer`, and `harness.efficiency` compute capability, process, and efficiency-adjusted scores.
5. `harness.reporter` writes JSON reports and prints summaries or cross-report comparisons.

## Public Source Of Truth

- Repo boundaries: `docs/architecture/monorepo-map.md`
- Hard rules: `docs/rules/invariants.md`
- Validation commands: `docs/validation/checks.md`
- Cleanup semantics: `docs/workflows/cleanup.md`
- Benchmark profile policy: `docs/quality/benchmark-profiles.md`

## Artifact Rules

- Scenario definitions are source; generated reports are not.
- Complex scoring logic belongs in `custom_checks/`, not in ad hoc runner branches.
- Live cleanup must happen after transcript capture, scoring, and report writing.
- Use `python3 run.py inventory ...` as the source of truth for current benchmark counts.
