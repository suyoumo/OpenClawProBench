# Security Policy

## Reporting

If you discover a security issue in OpenClawProBench, please avoid posting exploit details, credentials, or private environment data in a public issue.

If a private reporting channel is available with the maintainers, use it first. If no private channel is available, open a minimal public issue that states a security concern exists and request a secure follow-up path without including sensitive details.

## Scope

Please report issues such as:

- vulnerabilities in the benchmark harness
- unsafe handling of credentials or tokens in benchmark code
- fixture or scenario content that unintentionally exposes real secrets
- report-generation behavior that leaks sensitive runtime state unexpectedly

## Disclosure Guidance

- Redact secrets, tokens, API keys, and private URLs.
- Share only the minimum reproduction details needed to triage safely.
- Do not attach local OpenClaw state directories or credential-bearing config files publicly.
