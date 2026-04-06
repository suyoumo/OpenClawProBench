# tool_use_09_capability_boundary_live fixtures

Logical file sizes come from `dataset_manifest.json`, not from the tiny placeholder files on disk.

The calibrated version of this scenario is no longer a fixed three-shard copy task. The model must:

- infer read and exec limits from `boundary_observations.json`
- choose the lexicographically stable optimal safe bundle under the exec budget
- aggregate exact error statistics only over that chosen bundle
