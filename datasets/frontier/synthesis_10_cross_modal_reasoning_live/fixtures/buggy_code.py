def normalize_locale(raw_locale: str) -> str:
    normalized = raw_locale.replace("-", "_")
    language, region = normalized.split("_")
    return f"{language.lower()}_{region.upper()}"


def save_profile(payload: dict) -> dict:
    locale_key = normalize_locale(payload["locale"])
    return {"saved": True, "locale_key": locale_key}
