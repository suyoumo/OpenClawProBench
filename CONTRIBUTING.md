# Contributing

Thanks for contributing to OpenClawProBench.

## Setup

```bash
pip install uv
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

Make sure the local `openclaw` CLI is available before attempting live validation.

## Development Rules

- Keep grading deterministic.
- Prefer small, reviewable changes.
- Do not hand-edit generated files under `results/`.
- Keep scenario definitions declarative; put non-trivial grading logic in `custom_checks/`.
- Preserve cleanup ordering for live runs: transcript capture, scoring, report writing, then optional cleanup.

## Validation

Run the smallest relevant set:

```bash
python3 run.py inventory
python3 run.py dry
python3 -m unittest tests.test_runner tests.test_reporter tests.test_scoring
python3 -m unittest discover -s tests -t .
```

For scenario or custom-check changes, also run:

```bash
python3 run.py dry --scenario <SCENARIO_ID>
```

## Pull Requests

- Describe the problem and the behavioral change.
- List the validation commands you ran.
- Call out any report-schema or scenario-contract changes explicitly.
