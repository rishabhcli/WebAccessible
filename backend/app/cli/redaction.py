"""Defensive redaction for provider prose rendered to a caregiver terminal.

This is a second line of defence, not the primary control. The EverOS adapter
already keeps caregiver contact values out of search results and out of profile
update receipts. This module additionally removes contact-shaped and
token-shaped values from free-text fields before they reach stdout or a receipt
file, and reports how many values it replaced so nothing is altered silently.

Scope, deliberately narrow:

* Applied to prose only: routine names and descriptions, step instructions,
  irreversible descriptions, episode summaries, and profile item descriptions.
* Never applied to provider IDs, indexing status, selectors, origins, URLs,
  revisions, or timestamps. Those must survive exactly as EverOS returned them
  so replay and evidence stay traceable.
"""

from __future__ import annotations

import re
from typing import Final

CONTACT_PLACEHOLDER: Final = "[redacted-contact]"
TOKEN_PLACEHOLDER: Final = "[redacted-token]"

# A contact-shaped run: optional country prefix and 10-15 digits with the usual
# separators. Ten digits is the lower bound so ISO dates and money amounts are
# left alone. Newlines are excluded so a match cannot span lines.
_CONTACT_PATTERN: Final = re.compile(r"\+?\d[\d ().\-]{7,20}\d")
_CONTACT_MIN_DIGITS: Final = 10
_CONTACT_MAX_DIGITS: Final = 15

# A token-shaped run: 24 or more identifier characters containing both a letter
# and a digit. UUID-shaped runs are kept because WebAccessible uses UUIDs as
# readable skill, step, and session identifiers.
_TOKEN_PATTERN: Final = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?=[A-Za-z0-9_-]*[A-Za-z])"
    r"(?=[A-Za-z0-9_-]*\d)"
    r"[A-Za-z0-9_-]{24,}"
    r"(?![A-Za-z0-9_-])"
)
_UUID_PATTERN: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class Redactor:
    """Redacts prose for one command run and counts every replacement."""

    __slots__ = ("_count",)

    def __init__(self) -> None:
        self._count = 0

    @property
    def count(self) -> int:
        """Number of values replaced during this command run."""

        return self._count

    def text(self, value: str, *, limit: int | None = None) -> str:
        """Redact one prose string, optionally capping it at a model field limit."""

        redacted = _TOKEN_PATTERN.sub(self._replace_token, value)
        redacted = _CONTACT_PATTERN.sub(self._replace_contact, redacted)
        if limit is not None and len(redacted) > limit:
            redacted = redacted[:limit]
        return redacted

    def optional(self, value: str | None, *, limit: int | None = None) -> str | None:
        if value is None:
            return None
        return self.text(value, limit=limit)

    def _replace_token(self, match: re.Match[str]) -> str:
        candidate = match.group(0)
        if _UUID_PATTERN.fullmatch(candidate):
            return candidate
        self._count += 1
        return TOKEN_PLACEHOLDER

    def _replace_contact(self, match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits = sum(1 for character in candidate if character.isdigit())
        if not _CONTACT_MIN_DIGITS <= digits <= _CONTACT_MAX_DIGITS:
            return candidate
        self._count += 1
        return CONTACT_PLACEHOLDER
