# Task Flow

## Default Flow

1. Classify the task: docs, harness code, scenario content, or live integration.
2. Read `docs/architecture/index.md` and `docs/rules/invariants.md` before changing behavior.
3. Make the smallest change that keeps replay behavior deterministic and live cleanup safe.
4. Run the smallest relevant validation from `docs/validation/checks.md`.
5. Update public docs when the user-facing CLI, benchmark profiles, or runtime expectations change.

## Bugfix Flow

Use this when touching `run.py`, `harness/runner.py`, `harness/reporter.py`, `harness/models.py`, or `harness/live_harness.py`.

1. Identify whether the change affects CLI wiring, execution semantics, report schema, or cleanup timing.
2. If report fields change, update serialization, deserialization, output formatting, and tests together.
3. If live behavior changes, verify cleanup still happens after transcript capture and scoring.
4. Run unit tests and at least one CLI smoke.

## Scenario Flow

1. Update the YAML in `scenarios/`.
2. Add or adjust seeded assets in `datasets/` or `fixtures/` when the scenario contract changes.
3. Add `custom_checks/` logic only when YAML checks are insufficient.
4. Run `python3 run.py dry` plus the relevant tests.
