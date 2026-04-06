Incident: INC-4821
Window: 2026-03-20T00:00:00Z to 2026-03-21T00:00:00Z

Scope:
- only services `checkout` or `billing`
- only severity `high` or `critical`
- only status `confirmed`
- ignore anything under `archive/` or `samples/`

Outputs:
1. `incident_summary.json` with keys:
   - incident_id
   - affected_customers
   - highest_severity
   - source_files
   - evidence_count
2. `evidence.txt` with one line per matched event in this exact format:
   `timestamp | customer_id | service | error_code`

Sort requirements:
- `affected_customers` ascending
- `source_files` ascending
- `evidence.txt` lines ascending by timestamp
