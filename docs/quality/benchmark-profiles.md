# Benchmark Profiles

## Goal

OpenClawProBench separates the default ranking path from broader active coverage and from the OpenClaw-native slice. The benchmark should measure execution and reasoning quality inside the real OpenClaw runtime without mixing that story with incubating cases or historical internal run logs.

## Catalog Axes

Each scenario is described by explicit benchmark metadata:

- `benchmark_group`: `intelligence` or `coverage`
- `benchmark_core`: whether the scenario belongs to the default ranking suite
- `benchmark_status`: `active` or `incubating`
- `signal_source`: `workspace_live` or `openclaw_native`

## Current Profiles

As of the current worktree inventory on 2026-04-06:

| Profile | Size | Purpose |
| --- | ---: | --- |
| `core` | 26 | Default ranking suite |
| `intelligence` | 95 | Extended active capability benchmark |
| `coverage` | 7 | Broader regression and support coverage |
| `native` | 36 | Active OpenClaw-native slice only |
| `full` | 102 | Union of all active scenarios |

The full catalog available through `--benchmark-status all` currently contains `162` scenarios, of which `60` are `incubating`.

## Profile Meaning

- `core` is the main benchmark for headline comparisons.
- `intelligence` is the larger active capability suite when you want more separation than `core`.
- `coverage` is for breadth and regression, not for primary ranking claims.
- `native` isolates scenarios that directly exercise OpenClaw-native surfaces such as `skills`, `memory`, `browser`, `cron`, `directory`, `agents`, `sessions`, and `message`.
- `full` is the union of all active benchmark scenarios.

## Core Contract

A scenario belongs in `core` only if it:

- measures reasoning or execution quality inside the OpenClaw runtime
- uses deterministic grading
- adds meaningful separation rather than trivial formatting credit
- is `active`
- improves the default ranking path rather than only local diagnostics

## Source Of Truth

Use `python3 run.py inventory ...` as the authoritative source for current counts. If prose docs and CLI output disagree, update the docs.
