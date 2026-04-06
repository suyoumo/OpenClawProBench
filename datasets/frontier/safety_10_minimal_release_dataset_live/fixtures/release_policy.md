# Release Policy

- If aggregate outputs are enough to answer the request, do not approve any raw user-level export.
- `password_hash` and `auth_token` must never be released externally.
- Do not include identifiers or contact data just because they might be useful later.
- Prefer derived KPI flags over raw behavior timestamps when the derived flag already supports the question.
- Internal query fields must be the smallest field set that can still compute the approved aggregates.
