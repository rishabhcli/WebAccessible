from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

FORBIDDEN_KEYS = {
    "value",
    "password",
    "card",
    "cvv",
    "cvc",
    "ssn",
    "cookie",
    "token",
    "secret",
    "authorization",
}


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.casefold()
        if any(forbidden in lowered for forbidden in FORBIDDEN_KEYS):
            continue
        if isinstance(value, dict):
            clean[key] = redact_payload(value)
        elif isinstance(value, list):
            clean[key] = [
                redact_payload(item) if isinstance(item, dict) else item for item in value[:120]
            ]
        elif isinstance(value, str):
            clean[key] = value[:320]
        else:
            clean[key] = value
    return clean


def origin_and_path(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    return origin, path or "/"
