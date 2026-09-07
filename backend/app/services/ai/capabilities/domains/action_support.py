from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app.services.ai.capabilities.types import CapabilityError


ACTION_DRAFT_NAMESPACE = uuid.UUID("b2a2f707-3c7c-4f49-979e-d593106be7e7")
METADATA_FIELDS = (
    "warnings",
    "missing_fields",
    "unsupported_fields",
    "ambiguous_fields",
)
METADATA_PROPERTIES = {
    "warnings": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 300}},
    "missing_fields": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 64}},
    "unsupported_fields": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 64}},
    "ambiguous_fields": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 64}},
}


def action_schema(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": {**properties, **METADATA_PROPERTIES},
        "additionalProperties": False,
    }


def clean_optional_strings(payload: dict, fields: tuple[str, ...]) -> dict:
    result = dict(payload)
    for field_name in fields:
        value = result.get(field_name)
        if isinstance(value, str) and not value.strip():
            result.pop(field_name, None)
    return result


def bounded_decimal(
    value,
    field_name: str,
    minimum: Decimal,
    maximum: Decimal,
    *,
    nullable: bool = True,
) -> None:
    if value is None and nullable:
        return
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CapabilityError(
            "invalid_action_arguments", f"{field_name} no es válido.", 422
        ) from error
    if not number.is_finite() or number < minimum or number > maximum:
        raise CapabilityError(
            "invalid_action_arguments", f"{field_name} está fuera de rango.", 422
        )


def idempotency_uuid(draft_id: str, suffix: str) -> str:
    return str(uuid.uuid5(ACTION_DRAFT_NAMESPACE, f"{draft_id}:{suffix}"))


def aware_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def today_for_user(user) -> str:
    override = current_app.config.get("AI_TODAY_OVERRIDE")
    if hasattr(override, "isoformat"):
        return override.isoformat()
    timezone_name = user.timezone or current_app.config["APP_TIMEZONE"]
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise CapabilityError("invalid_timezone", "La zona horaria de la cuenta no es válida.") from error
    return datetime.now(timezone.utc).astimezone(zone).date().isoformat()


def preview_field(
    name: str,
    label: str,
    value,
    *,
    kind: str = "text",
    required: bool = False,
    options: tuple[str, ...] = (),
) -> dict:
    return {
        "name": name,
        "label": label,
        "value": value,
        "kind": kind,
        "required": required,
        "options": list(options),
    }
