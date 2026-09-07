from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app.extensions import db
from app.models import UserGoal
from app.services.ai.capabilities.domains.action_support import (
    METADATA_FIELDS,
    action_schema,
    bounded_decimal,
    clean_optional_strings,
    idempotency_uuid,
    preview_field,
    today_for_user,
)
from app.services.ai.capabilities.types import ActionApplyResult, ActionCapability, CapabilityError
from app.services.engagement import create_goal, patch_goal


GOAL_TYPES = (
    "training_sessions_per_week",
    "active_days_per_week",
    "daily_steps",
    "nutrition_calories",
    "nutrition_protein",
    "nutrition_carbohydrates",
    "nutrition_fat",
    "weight_logging_frequency",
)
GOAL_DEFAULTS = {
    "training_sessions_per_week": ("session", "weekly"),
    "active_days_per_week": ("day", "weekly"),
    "daily_steps": ("step", "daily"),
    "nutrition_calories": ("kcal", "daily"),
    "nutrition_protein": ("g", "daily"),
    "nutrition_carbohydrates": ("g", "daily"),
    "nutrition_fat": ("g", "daily"),
    "weight_logging_frequency": ("log", "weekly"),
}
GOAL_UNIT_ALIASES = {
    "sessions": "session",
    "sesiones": "session",
    "days": "day",
    "días": "day",
    "dias": "day",
    "steps": "step",
    "pasos": "step",
    "calories": "kcal",
    "calorías": "kcal",
    "calorias": "kcal",
    "grams": "g",
    "gramos": "g",
    "logs": "log",
    "registros": "log",
}
GOAL_FIELDS = (
    "goal_type",
    "target_value",
    "unit",
    "period",
    "applicable_days",
    "timezone",
    "start_date",
    "end_date",
    "state",
    *METADATA_FIELDS,
)
GOAL_SCHEMA = action_schema(
    {
        "goal_type": {"type": "string", "enum": list(GOAL_TYPES)},
        "target_value": {"type": ["string", "number"]},
        "unit": {
            "type": "string",
            "enum": ["session", "day", "step", "kcal", "g", "log"],
        },
        "period": {
            "type": "string",
            "enum": ["daily", "weekly", "selected_days"],
        },
        "applicable_days": {
            "type": "array",
            "maxItems": 7,
            "items": {"type": "integer", "minimum": 1, "maximum": 7},
            "uniqueItems": True,
        },
        "timezone": {"type": "string", "maxLength": 64},
        "start_date": {"type": "string", "format": "date"},
        "end_date": {"type": ["string", "null"], "format": "date"},
        "state": {
            "type": "string",
            "enum": ["active", "paused", "completed", "archived"],
        },
    }
)


def _normalize_common(_user, payload: dict) -> dict:
    clean = clean_optional_strings(payload, ("unit", "period", "timezone", "start_date", "end_date", "state"))
    if clean.get("unit"):
        unit_key = clean["unit"].strip().lower()
        clean["unit"] = GOAL_UNIT_ALIASES.get(unit_key, unit_key)
    goal_type = clean.get("goal_type")
    if goal_type in GOAL_DEFAULTS:
        unit, period = GOAL_DEFAULTS[goal_type]
        if "unit" in clean and clean["unit"] != unit:
            raise CapabilityError("invalid_goal_contract", "La unidad no corresponde al tipo de meta.", 422)
        if "period" in clean and clean["period"] not in {period, "selected_days"}:
            raise CapabilityError("invalid_goal_contract", "El periodo no corresponde al tipo de meta.", 422)
    if clean.get("target_value") is not None:
        bounded_decimal(
            clean["target_value"],
            "target_value",
            Decimal("0.001"),
            Decimal("1000000"),
            nullable=False,
        )
    if clean.get("timezone"):
        try:
            ZoneInfo(clean["timezone"])
        except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
            raise CapabilityError(
                "invalid_timezone", "La zona horaria de la meta no es válida.", 422
            ) from error
    if clean.get("start_date") and clean.get("end_date"):
        try:
            if date.fromisoformat(clean["end_date"]) < date.fromisoformat(clean["start_date"]):
                raise CapabilityError(
                    "invalid_date_range", "La fecha final no puede ser anterior a la inicial.", 422
                )
        except (TypeError, ValueError) as error:
            raise CapabilityError(
                "invalid_date_range", "Las fechas de la meta no son válidas.", 422
            ) from error
    return clean


def _normalize_create(user, payload: dict) -> dict:
    clean = _normalize_common(user, payload)
    goal_type = clean.get("goal_type")
    if goal_type in GOAL_DEFAULTS:
        unit, period = GOAL_DEFAULTS[goal_type]
        clean.setdefault("unit", unit)
        clean.setdefault("period", period)
    clean.setdefault("timezone", user.timezone or current_app.config["APP_TIMEZONE"])
    clean.setdefault("start_date", today_for_user(user))
    return clean


def _goal_context(user, payload: dict, resource_context=None) -> dict:
    goal_type = payload.get("goal_type")
    if not goal_type and not resource_context:
        return {}
    statement = db.select(UserGoal).where(
        UserGoal.user_id == user.id,
        UserGoal.state != "archived",
    )
    if resource_context:
        if resource_context.get("resource_type") != "user_goal":
            raise CapabilityError(
                "invalid_action_context", "El contexto no corresponde a una meta.", 403
            )
        statement = statement.where(
            UserGoal.public_id == resource_context.get("resource_public_id")
        )
    else:
        statement = statement.where(UserGoal.goal_type == goal_type).order_by(
            UserGoal.start_date.desc(), UserGoal.id.desc()
        ).limit(1)
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None:
        if resource_context:
            raise CapabilityError(
                "action_context_not_found",
                "La meta contextual no está disponible para esta cuenta.",
                404,
            )
        return {"needs_input": True, "resolution_code": "goal_not_found"}
    if goal_type and goal_type != row.goal_type:
        raise CapabilityError(
            "invalid_action_context", "La meta propuesta no coincide con el contexto seguro.", 422
        )
    return {
        "resource_type": "user_goal",
        "public_id": row.public_id,
        "base_revision": row.revision,
        "argument_defaults": {"goal_type": row.goal_type},
        "original": {
            "goal_type": row.goal_type,
            "target_value": format(row.target_value, "f"),
            "unit": row.unit,
            "period": row.period,
            "state": row.state,
        },
    }


def _preview(_user, payload: dict, context) -> dict:
    labels = {
        "goal_type": "Tipo de meta",
        "target_value": "Objetivo",
        "unit": "Unidad",
        "period": "Periodo",
        "applicable_days": "Días aplicables",
        "timezone": "Zona horaria",
        "start_date": "Fecha de inicio",
        "end_date": "Fecha de fin",
        "state": "Estado",
    }
    fields = [
        preview_field(
            name,
            label,
            payload.get(name),
            kind="date" if name in {"start_date", "end_date"} else "text",
            required=name in {"goal_type", "target_value"},
            options=GOAL_TYPES if name == "goal_type" else (),
        )
        for name, label in labels.items()
    ]
    return {"fields": fields, "original": context.get("original")}


def apply_goal_create(user, draft, payload: dict, _context, _now) -> ActionApplyResult:
    document = {
        key: value
        for key, value in payload.items()
        if key not in METADATA_FIELDS
    }
    document["public_id"] = idempotency_uuid(draft.public_id, "goal")
    row = create_goal(user.id, document)
    return ActionApplyResult("user_goal", (row.public_id,))


def apply_goal_update(user, _draft, payload: dict, context, _now) -> ActionApplyResult:
    document = {
        key: value
        for key, value in payload.items()
        if key not in METADATA_FIELDS and key != "goal_type"
    }
    document["base_revision"] = context.get("base_revision")
    row = patch_goal(user.id, context.get("public_id"), document)
    return ActionApplyResult("user_goal", (row.public_id,))


GOAL_CREATE = ActionCapability(
    action_id="goal.create",
    domain="goals",
    entity="user_goal",
    operation="create",
    label="Crear meta",
    description="Prepara una meta compatible con los tipos existentes.",
    supported_fields=GOAL_FIELDS,
    required_fields=("goal_type", "target_value", "unit", "period", "timezone", "start_date"),
    optional_fields=tuple(
        field
        for field in GOAL_FIELDS
        if field not in {"goal_type", "target_value", "unit", "period", "timezone", "start_date"}
    ),
    input_schema=GOAL_SCHEMA,
    apply_handler=apply_goal_create,
    normalizer=_normalize_create,
    previewer=_preview,
)

GOAL_UPDATE = ActionCapability(
    action_id="goal.update",
    domain="goals",
    entity="user_goal",
    operation="update",
    label="Cambiar meta",
    description="Prepara una actualización owner-only de una meta existente.",
    supported_fields=GOAL_FIELDS,
    required_fields=("goal_type", "target_value"),
    optional_fields=tuple(field for field in GOAL_FIELDS if field not in {"goal_type", "target_value"}),
    input_schema=GOAL_SCHEMA,
    apply_handler=apply_goal_update,
    normalizer=_normalize_common,
    owner_resolver=_goal_context,
    previewer=_preview,
    required_read_capabilities=("get_goals_summary",),
    idempotency_policy="owner_revision",
)
