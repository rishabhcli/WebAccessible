from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.app.config import Settings
from backend.app.contracts.models import (
    ParticipantSessionRequest,
    ParticipantSessionResponse,
)
from backend.app.persistence.repository import OperationalRepository


@dataclass(frozen=True)
class AuthenticatedParticipant:
    participant_session_id: UUID
    user_id: str
    role: str
    participant_name: str


class ParticipantAuthService:
    def __init__(self, settings: Settings, repository: OperationalRepository) -> None:
        configured = settings.session_signing_secret
        if configured:
            secret = configured.get_secret_value()
        elif settings.app_env.value in {"demo", "production"}:
            raise RuntimeError("SESSION_SIGNING_SECRET is required in demo and production")
        else:
            secret = secrets.token_urlsafe(48)
        self.repository = repository
        self.ttl_seconds = 8 * 60 * 60
        self.serializer = URLSafeTimedSerializer(secret, salt="webaccessible-participant-v1")

    def create(self, request: ParticipantSessionRequest) -> ParticipantSessionResponse:
        participant_id = uuid4()
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        self.repository.create_participant(
            participant_id=participant_id,
            user_id=request.user_id,
            role=request.role.value,
            participant_name=request.participant_name,
            preferences={
                "reading_size": request.reading_size,
                "voice_enabled": request.voice_enabled,
                "caregiver_mobile": request.caregiver_mobile,
                "timezone": request.timezone,
            },
            expires_at=expires_at,
        )
        token = self.serializer.dumps(
            {
                "participant_session_id": str(participant_id),
                "user_id": request.user_id,
                "role": request.role.value,
            }
        )
        return ParticipantSessionResponse(
            participant_session_id=participant_id,
            access_token=token,
            expires_at=expires_at,
            user_id=request.user_id,
            role=request.role,
        )

    def verify(self, token: str) -> AuthenticatedParticipant:
        try:
            payload: Any = self.serializer.loads(token, max_age=self.ttl_seconds)
        except SignatureExpired as error:
            raise PermissionError("participant session expired") from error
        except BadSignature as error:
            raise PermissionError("participant session is invalid") from error
        if not isinstance(payload, dict):
            raise PermissionError("participant session is invalid")
        participant_id = UUID(str(payload.get("participant_session_id")))
        stored = self.repository.get_participant(participant_id)
        if stored is None:
            raise PermissionError("participant session is unavailable")
        if datetime.fromisoformat(stored["expires_at"]) <= datetime.now(UTC):
            raise PermissionError("participant session expired")
        if stored["user_id"] != payload.get("user_id") or stored["role"] != payload.get("role"):
            raise PermissionError("participant session binding is invalid")
        return AuthenticatedParticipant(
            participant_session_id=participant_id,
            user_id=stored["user_id"],
            role=stored["role"],
            participant_name=stored["participant_name"],
        )
