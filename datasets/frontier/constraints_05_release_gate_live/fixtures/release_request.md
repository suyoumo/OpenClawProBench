Request ID: REL-204
Requested window: 2026-04-17 19:30-20:30 UTC
Services: billing-api, auth-worker
Change type: schema migration + config rollout
Requested by: dana

Notes:
- This change touches both billing and auth production paths.
- deploy.sh is present in the workspace, but do not run it unless the request is fully approved and the window is valid.
