from __future__ import annotations

from backend.app.contracts.models import SessionState

ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {
        SessionState.OBSERVING,
        SessionState.PROVIDER_UNAVAILABLE,
        SessionState.FAILED,
    },
    SessionState.OBSERVING: {
        SessionState.HELP_OFFERED,
        SessionState.GUIDING,
        SessionState.REPAIRING,
        SessionState.SAFETY_PAUSED,
        SessionState.COMPLETED,
        SessionState.PREPARED,
        SessionState.ESCALATED,
        SessionState.ABANDONED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.HELP_OFFERED: {
        SessionState.OBSERVING,
        SessionState.GUIDING,
        SessionState.SAFETY_PAUSED,
        SessionState.ABANDONED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.GUIDING: {
        SessionState.AWAITING_USER_ACTION,
        SessionState.SAFETY_PAUSED,
        SessionState.ESCALATED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.AWAITING_USER_ACTION: {
        SessionState.VERIFYING,
        SessionState.REROUTING,
        SessionState.SAFETY_PAUSED,
        SessionState.ABANDONED,
        SessionState.ESCALATED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.VERIFYING: {
        SessionState.GUIDING,
        SessionState.OBSERVING,
        SessionState.REROUTING,
        SessionState.REPAIRING,
        SessionState.SAFETY_PAUSED,
        SessionState.COMPLETED,
        SessionState.PREPARED,
        SessionState.ESCALATED,
        SessionState.FAILED,
    },
    SessionState.REROUTING: {
        SessionState.GUIDING,
        SessionState.REPAIRING,
        SessionState.SAFETY_PAUSED,
        SessionState.ESCALATED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.REPAIRING: {
        SessionState.GUIDING,
        SessionState.SAFETY_PAUSED,
        SessionState.ESCALATED,
        SessionState.FAILED,
        SessionState.PROVIDER_UNAVAILABLE,
    },
    SessionState.SAFETY_PAUSED: {
        SessionState.OBSERVING,
        SessionState.VERIFYING,
        SessionState.ESCALATED,
        SessionState.PREPARED,
        SessionState.ABANDONED,
        SessionState.FAILED,
    },
    SessionState.PROVIDER_UNAVAILABLE: {
        SessionState.OBSERVING,
        SessionState.ABANDONED,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),
    SessionState.PREPARED: set(),
    SessionState.ESCALATED: set(),
    SessionState.ABANDONED: set(),
    SessionState.FAILED: set(),
}


class InvalidStateTransition(ValueError):
    pass


def ensure_transition(current: SessionState, target: SessionState) -> None:
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition from {current.value} to {target.value}")
