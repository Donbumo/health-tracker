from __future__ import annotations

from dataclasses import dataclass
import uuid

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from app.services.ai.capabilities.types import CapabilityError


_CONTEXT_SALT = "health-tracker-ai-action-context-v1"


@dataclass(frozen=True)
class AIActionContext:
    """Signed, owner-bound resource reference for contextual AI entry points."""

    action_capability_id: str
    domain: str
    resource_type: str
    resource_public_id: str

    def as_mapping(self) -> dict[str, str]:
        return {
            "action_capability_id": self.action_capability_id,
            "domain": self.domain,
            "resource_type": self.resource_type,
            "resource_public_id": self.resource_public_id,
        }


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_CONTEXT_SALT)


def issue_action_context_token(
    *,
    user_id: int,
    action_capability_id: str,
    domain: str,
    resource_type: str,
    resource_public_id: str,
) -> str:
    try:
        public_id = str(uuid.UUID(str(resource_public_id)))
    except (TypeError, ValueError, AttributeError) as error:
        raise CapabilityError(
            "invalid_action_context", "El recurso contextual no es válido."
        ) from error
    values = {
        "v": 1,
        "uid": int(user_id),
        "action": str(action_capability_id),
        "domain": str(domain),
        "resource_type": str(resource_type),
        "resource_id": public_id,
    }
    if any(not values[key] or len(values[key]) > 96 for key in ("action", "domain", "resource_type")):
        raise CapabilityError("invalid_action_context", "El recurso contextual no es válido.")
    return _serializer().dumps(values)


def load_action_context_token(token: str, *, user_id: int) -> AIActionContext:
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise CapabilityError("invalid_action_context", "El contexto de la acción no es válido.")
    maximum_age = current_app.config.get("AI_ACTION_CONTEXT_MAX_AGE_SECONDS", 900)
    if type(maximum_age) is not int or not 60 <= maximum_age <= 86_400:
        raise CapabilityError(
            "invalid_ai_configuration", "La configuración AI no es válida.", 503
        )
    try:
        values = _serializer().loads(token, max_age=maximum_age)
        if not isinstance(values, dict) or set(values) != {
            "v", "uid", "action", "domain", "resource_type", "resource_id"
        }:
            raise ValueError
        if values["v"] != 1 or values["uid"] != user_id:
            raise ValueError
        public_id = str(uuid.UUID(str(values["resource_id"])))
        for key in ("action", "domain", "resource_type"):
            if not isinstance(values[key], str) or not values[key] or len(values[key]) > 96:
                raise ValueError
    except (BadData, TypeError, ValueError, AttributeError) as error:
        raise CapabilityError(
            "invalid_action_context",
            "El contexto de la acción expiró o no pertenece a esta cuenta.",
            403,
        ) from error
    return AIActionContext(
        action_capability_id=values["action"],
        domain=values["domain"],
        resource_type=values["resource_type"],
        resource_public_id=public_id,
    )
