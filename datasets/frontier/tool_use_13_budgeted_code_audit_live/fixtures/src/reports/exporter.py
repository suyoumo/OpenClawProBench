def write_audit_row(headers: dict[str, str]) -> str:
    auth = headers.get("Authorization", "")
    return f"audit auth={auth}"
