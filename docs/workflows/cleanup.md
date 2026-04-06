# Cleanup

## Principles

- Preserve benchmark evidence before deleting anything.
- Cleanup should reduce disk drift, not hide failures.
- Generated outputs should be safe to delete after the run is fully reported.

## Generated State

- JSON reports under `results/`
- Temporary per-trial workspaces created by the runner
- Live-agent sessions and transcripts under the selected OpenClaw state tree

## Cleanup Rules

1. Do not delete live agents before transcript capture, scoring, and report writing complete.
2. Use `--cleanup-agents` only when the run no longer needs agent workspaces for debugging.
3. Treat `results/*.json` as generated artifacts; remove them by deletion, not by hand-editing.
4. If a run crashes before reporting, preserve the workspace and stderr long enough to diagnose the failure.
5. When adding cleanup behavior, document the trigger point and verify it with a targeted regression or smoke.
