# Declared Pipeline Graph

`data_collection -> data_cleaning -> feature_extraction -> model_prediction -> result_output`

## Contract Notes

- The official canonical key becomes `id` after `data_cleaning`.
- `result_output` is documented as consuming only `predictions.json`.
- No declared edge exists from `data_collection` to `result_output`.
- Any direct use of `collected_data.json` inside `result_output` is an undeclared hidden dependency.
