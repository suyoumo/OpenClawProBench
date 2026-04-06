# Monorepo Map

| Path | Layer / Owner | Boundary | Depends On | Notes |
| --- | --- | --- | --- | --- |
| `run.py` | CLI control plane | Parses user input and delegates to harness modules; should stay thin | `harness.loader`, `harness.runner`, `harness.reporter` | Add new flags here only when the underlying behavior already exists below |
| `harness/` | Core benchmark engine | Owns loading, execution, scoring, reporting, and result schemas | `scenarios/`, `custom_checks/`, `config/` | Most benchmark logic changes belong here |
| `harness/live_harness.py` | Live execution bridge | Owns OpenClaw process lifecycle, transcript loading, and optional agent cleanup | OpenClaw CLI, local workspace paths | Cleanup must happen after scoring artifacts are captured |
| `scenarios/` | Benchmark content layer | YAML only; defines prompts, tools, checks, workspace seeds, scripts, and execution mode | `fixtures/`, `datasets/`, optional `custom_checks/` | Scenario IDs are stable keys for resume and report reuse |
| `custom_checks/` | Scenario-specific grading layer | Use only when YAML checks are insufficient | `harness.custom_checks`, workspace artifacts, transcripts | Imported OIB5 checks may provide both `grade()` and `grade_process()` |
| `fixtures/` | Replay asset layer | Read-only replay traces and native static task inputs | none | Do not mutate during benchmark runs |
| `datasets/` | Imported live asset layer | Seed directories plus optional setup and teardown scripts for live scenarios | none | Treat as read-only source material copied into per-trial workspaces |
| `mock_tools/` | Replay support service | Supports deterministic local development and mock-backed tests | FastAPI runtime when used directly | Not used for live OpenClaw execution |
| `tests/` | Regression layer | Validates loader, scoring, runner, and server behavior | `harness/`, `mock_tools/` | Add tests when schema or execution semantics change |
| `results/` | Generated artifact layer | Stores runtime reports only; do not treat as editable source | `harness.reporter` | Generated at runtime and normally gitignored |
| `config/` | Configuration layer | Pricing and OpenClaw config templates | none | Keep pricing format compatible with runner normalization |
| `scripts/` | Auxiliary tooling | Local helper scripts and ad hoc validation | project modules | Avoid putting production logic here when it belongs in `harness/` |

## Boundary Notes

- Ownership boundary: `harness.models` defines the report schema, so any report-field addition must update serialization, deserialization, reporter output, and tests together.
- Dependency boundary: `scenarios/`, `fixtures/`, and `datasets/` should remain declarative; business logic should not leak into YAML.
- Execution boundary: replay and live paths may share scoring, but their setup and cleanup semantics differ and must be documented explicitly.
