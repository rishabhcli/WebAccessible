"""Machine-readable receipts for the caregiver memory administration CLI.

Every command produces exactly one receipt so a later caregiver UI can render
the same outcome the terminal showed without re-reading EverOS. A receipt
records what the provider actually did, including the cases where the provider
could not do it.

A receipt never carries provider credentials, provider request bodies, caregiver
contact values, or uploaded document content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Final

RECEIPT_VERSION: Final = "1.0"
TOOL_NAME: Final = "webaccessible-memory"
TOOL_VERSION: Final = "0.1.0"
PROVIDER_NAME: Final = "everos"


class ExitCode(IntEnum):
    """Process exit codes. ``2`` is shared with argparse usage failures."""

    OK = 0
    UNEXPECTED = 1
    REFUSED = 2
    PROVIDER_LIMITATION = 3
    NOT_FOUND = 4
    PROVIDER_UNAVAILABLE = 5
    INVALID_PROVIDER_DATA = 6
    UNCONFIGURED = 7


class ReceiptStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    REFUSED = "refused"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID_PROVIDER_DATA = "invalid_provider_data"
    UNCONFIGURED = "unconfigured"


@dataclass(slots=True)
class ReceiptError:
    """A sanitized failure description safe to print, store, and render later."""

    code: str
    message: str
    retryable: bool = False
    provider_status_code: int | None = None

    def to_json_object(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "provider_status_code": self.provider_status_code,
        }


@dataclass(slots=True)
class Receipt:
    """The single result envelope every CLI command produces."""

    command: str
    status: ReceiptStatus = ReceiptStatus.OK
    exit_code: ExitCode = ExitCode.OK
    user_id: str | None = None
    agent_memory_scope: str | None = None
    memory_changed: bool = False
    provider_limitation: str | None = None
    redaction_count: int = 0
    notes: list[str] = field(default_factory=list)
    error: ReceiptError | None = None
    data: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_note(self, note: str) -> None:
        self.notes.append(note)

    def to_json_object(self) -> dict[str, Any]:
        return {
            "receipt_version": RECEIPT_VERSION,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "provider": PROVIDER_NAME,
            "command": self.command,
            "status": self.status.value,
            "exit_code": int(self.exit_code),
            "generated_at": self.generated_at.isoformat(),
            "user_id": self.user_id,
            "agent_memory_scope": self.agent_memory_scope,
            "memory_changed": self.memory_changed,
            "provider_limitation": self.provider_limitation,
            "redaction_count": self.redaction_count,
            "notes": list(self.notes),
            "error": self.error.to_json_object() if self.error is not None else None,
            "data": self.data,
        }


def render_receipt_json(receipt: Receipt) -> str:
    """Return the pretty-printed receipt document, newline terminated."""

    return json.dumps(receipt.to_json_object(), indent=2, ensure_ascii=False) + "\n"
