# error_recovery_07_partial_success - Fixtures

This directory contains test data for the error_recovery_07_partial_success scenario.

## Workspace Inputs

- `file_list.txt`: all `1000` expected input files (`file_0001.dat` .. `file_1000.dat`)
- `processed_files.csv`: exported rows from the `processed_files` table
- `process.log`: one bounded run log showing the late-stage timeout burst

## Ground Truth

- Successful files: `700`
- Partial files needing cleanup: `18` (`file_0701.dat` .. `file_0718.dat`)
- Failed files needing retry without cleanup: `282` (`file_0719.dat` .. `file_1000.dat`)
- Root cause: database connection pool exhaustion leading to connection timeouts once the pool reaches `32/32`

The prompt intentionally asks the model to reconcile these three inputs instead of inventing missing data.
