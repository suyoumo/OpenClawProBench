# Validation Checks

Run the smallest relevant set for the surface you changed.

## Inventory And Schema

```bash
python3 run.py inventory
python3 run.py inventory --json
python3 run.py inventory --benchmark-status all --json
python3 run.py inventory --benchmark-profile core
python3 run.py inventory --benchmark-profile native
python3 run.py dry
```

Use this after changing scenario loading, benchmark-profile selection, scenario metadata, or CLI filters.

## Full Unit Regression

```bash
python3 -m unittest discover -s tests -t .
```

Run this after changes in `harness/`, `custom_checks/`, `mock_tools/`, or shared scenario schema behavior.

## Targeted Harness Regression

```bash
python3 -m unittest tests.test_runner tests.test_reporter tests.test_scoring
python3 -m unittest tests.test_cli tests.test_loader
```

Use this after touching execution semantics, reporting, summary aggregation, resume behavior, or loader/filter logic.

## Scenario-Focused Regression

```bash
python3 run.py dry --scenario <SCENARIO_ID>
python3 -m unittest tests.test_scoring
python3 -m unittest tests.test_loader
```

Use this when tightening a specific scenario or custom grader.

## Live Smoke

```bash
python3 run.py run --model '<MODEL>' --execution-mode live --benchmark-profile core --trials 1 --cleanup-agents
python3 run.py run --model '<MODEL>' --execution-mode live --scenario tool_use_02_workspace_extract_live --trials 1 --cleanup-agents
```

Use only when the local OpenClaw environment is available. Prefer dry and unit validation first.

## Resume Smoke

```bash
python3 run.py run --model '<MODEL>' --execution-mode live --benchmark-profile core --trials 1 --continue
python3 run.py run --model '<MODEL>' --execution-mode live --benchmark-profile core --trials 1 --resume-from results/result_<MODEL>_<TIMESTAMP>.json
python3 run.py run --model '<MODEL>' --execution-mode live --benchmark-profile core --trials 1 --continue --rerun-execution-failures
```

Use this after changing checkpointing, report reuse, or failure-requeue behavior.

## Report Utilities

```bash
python3 run.py compare --results-dir results
python3 scripts/index_results.py
```
