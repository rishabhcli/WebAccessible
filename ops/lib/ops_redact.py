#!/usr/bin/env python3
"""Single redaction implementation shared by every WebAccessible ops check.

Requirement: no ops output may expose credentials or provider capability URLs.
"Capability URL" means any URL that, on its own, grants control of a live
provider resource: a Browserbase CDP/``wss://`` connect URL, a Live View or
devtools debugger URL, or any signed URL carrying a token in its query string.

This module is stdlib-only so the Bash checks can pipe through it with the
system ``python3`` while the Python checks import ``redact`` directly. Keep this
file as the only place redaction rules are defined.

Usage as a filter:

    some-command | python3 ops/lib/ops_redact.py

Usage as a module:

    from ops_redact import redact
    print(redact(text))

Self test (touches no provider, no network):

    python3 ops/lib/ops_redact.py --self-test
"""

from __future__ import annotations

import re
import sys
from typing import Final

# Characters that may appear inside a URL for redaction purposes. Stops at
# whitespace and at the punctuation that normally terminates a URL in prose,
# JSON, or shell output.
_URL: Final = r"[^\s\"'<>|)\]}]"

REDACTED_CDP: Final = "[redacted:cdp-url]"
REDACTED_LIVE_VIEW: Final = "[redacted:live-view-url]"
REDACTED_QUERY: Final = "?[redacted:query]"
REDACTED_VALUE: Final = "[redacted]"

# Ordered rules. Labelled secrets are removed first so no later rule can see a
# placeholder as its input and emit a doubly-redacted fragment. The `(?!\[redacted)`
# guards exist for the same reason.
_RULES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # PEM private keys, including multi-line blocks.
    (
        re.compile(
            r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[redacted:private-key]",
    ),
    # key=value / "key": "value" / KEY: value for secret-shaped names. The
    # optional `Bearer` prefix keeps an Authorization header on one placeholder.
    (
        re.compile(
            r"((?:x-[a-z0-9-]*-)?(?:api[_-]?key|apikey|token|access[_-]?token|"
            r"refresh[_-]?token|secret|password|passwd|pwd|signing[_-]?key|"
            r"private[_-]?key|connect[_-]?url|authorization|credential)"
            r"[\"']?\s*[:=]\s*[\"']?)(?!\[redacted)((?:Bearer\s+)?[^\s\"',;)\]}]+)",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED_VALUE}",
    ),
    # Authorization headers that were not written as key=value.
    (
        re.compile(r"\bBearer\s+(?!\[redacted)[A-Za-z0-9._\-]+", re.IGNORECASE),
        f"Bearer {REDACTED_VALUE}",
    ),
    # Chrome DevTools Protocol / websocket connect URLs.
    (re.compile(rf"wss?://{_URL}+", re.IGNORECASE), REDACTED_CDP),
    # Browserbase Live View, devtools, and session-connect capability URLs.
    (
        re.compile(
            rf"https?://{_URL}*?(?:devtools|/debug|connect\.browserbase){_URL}*",
            re.IGNORECASE,
        ),
        REDACTED_LIVE_VIEW,
    ),
    # Any remaining URL keeps its origin and path but loses its query string,
    # which is where signed capability tokens live.
    (
        re.compile(
            rf"(https?://{_URL}*?)\?(?!{_URL}*\[redacted){_URL}+",
            re.IGNORECASE,
        ),
        rf"\1{REDACTED_QUERY}",
    ),
    # Known provider key shapes, even when they appear without a label.
    (re.compile(r"\bbb_(?:live|test)_[A-Za-z0-9_\-]{6,}"), "bb_[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"), "[redacted:api-key]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "[redacted:jwt]",
    ),
)

# Values that must never survive redaction, used by --self-test.
_SELF_TEST_CASES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "connect_url=wss://connect.browserbase.com/v1?apiKey=bb_live_ABCDEF123456",
        ("wss://", "bb_live_", "apiKey=bb"),
    ),
    (
        "liveView https://www.browserbase.com/devtools-fullscreen/inspector.html?wss=x1y2",
        ("devtools", "wss=x1y2"),
    ),
    (
        '{"debuggerUrl": "https://connect.browserbase.com/debug/abc123"}',
        ("connect.browserbase.com", "abc123"),
    ),
    (
        "SNOWFLAKE_PASSWORD=hunter2-not-a-real-secret",
        ("hunter2-not-a-real-secret",),
    ),
    (
        "X-BB-API-Key: bb_live_ZZZZZZZZZZZZ",
        ("bb_live_Z",),
    ),
    (
        "Authorization: Bearer eyJhbGciOi.eyJzdWIi.sIgnAtUrE",
        ("eyJhbGciOi", "sIgnAtUrE"),
    ),
    (
        "everos api_key = ev-secret-value-1234567890",
        ("ev-secret-value-1234567890",),
    ),
    (
        "https://webaccessible-care.fly.dev/v1/live-view?token=abc.def.ghi",
        ("token=abc", "abc.def.ghi"),
    ),
)


def redact(text: str) -> str:
    """Return ``text`` with credentials and provider capability URLs removed."""

    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def _self_test() -> int:
    failures: list[str] = []
    for raw, forbidden in _SELF_TEST_CASES:
        cleaned = redact(raw)
        leaked = [needle for needle in forbidden if needle in cleaned]
        status = "leaked" if leaked else "ok"
        print(f"[{status}] {cleaned}")
        if leaked:
            failures.append(f"{leaked!r} survived redaction")
        if "]]" in cleaned or "[redacted:query]]" in cleaned:
            failures.append(f"redaction left a malformed placeholder in {cleaned!r}")
    # A safe operational URL must stay readable so runbooks remain usable.
    kept = redact("https://webaccessible-care.fly.dev/health")
    print(f"[keep ] {kept}")
    if kept != "https://webaccessible-care.fly.dev/health":
        failures.append("a plain health URL was over-redacted")
    if failures:
        for failure in failures:
            print(f"self-test failure: {failure}", file=sys.stderr)
        return 1
    print("redaction self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return _self_test()
    sys.stdout.write(redact(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
