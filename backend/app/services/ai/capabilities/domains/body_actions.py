from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models import WeighIn
from app.services.ai.capabilities.domains.action_support import (
    METADATA_FIELDS,
    action_schema,
    aware_iso,
    bounded_decimal,
    clean_optional_strings,
    idempotency_uuid,
    preview_field,
)
from app.services.ai.capabilities.types import ActionApplyResult, ActionCapability, CapabilityError
from app.services.mobile_health import create_body_stat, patch_body_stat


BODY_LIMITS = {
    "weight": (Decimal("0.001"), Decimal("700")),
    "body_fat_percent": (Decimal("0"), Decimal("100")),
    "muscle_mass_kg": (Decimal("0"), Decimal("1000")),
    "water_percent": (Decimal("0"), Decimal("100")),
    "visceral_fat": (Decimal("0"), Decimal("1000")),
    "bmr_kcal": (Decimal("0"), Decimal("100000")),
    "bmi": (Decimal("0"), Decimal("1000")),
}
BODY_FIELDS = (
    "weight",
    "unit",
    "recorded_at",
    "body_fat_percent",
    "muscle_mass_kg",
    "water_percent",
    "visceral_fat",
    "bmr_kcal",
    "bmi",
    "notes",
    *METADATA_FIELDS,
)
BODY_SCHEMA = action_schema(
    {
        "weight": {"type": ["string", "number"]},
        "unit": {"type": "string", "enum": ["kg", "lb"]},
        "recorded_at": {"type": "string", "format": "date-time"},
        **{
            name: {"type": ["string", "number", "null"]}
            for name in BODY_LIMITS
            if name != "weight"
        },
        "notes": {"type": ["string", "null"], "maxLength": 2000},
    }
)


def _normalize(_user, payload: dict) -> dict:
    clean = clean_optional_strings(
        payload,
        (
            "recorded_at",
            "body_fat_percent",
            "muscle_mass_kg",
            "water_percent",
            "visceral_fat",
            "bmr_kcal",
            "bmi",
            "notes",
        ),
    )
    for field_name, (minimum, maximum) in BODY_LIMITS.items():
        if field_name in clean:
            bounded_decimal(
                clean[field_name], field_name, minimum, maximum, nullable=field_name != "weight"
            )
    return clean


def _latest_body_context(user, _payload: dict, resource_context=None) -> dict:
    statement = db.select(WeighIn).where(WeighIn.user_id == user.id)
    if resource_context:
        if resource_context.get("resource_type") != "body_stat":
            raise CapabilityError(
                "invalid_action_context", "El contexto no corresponde a una medición corporal.", 403
            )
        statement = statement.where(
            WeighIn.public_id == resource_context.get("resource_public_id")
        )
    else:
        statement = statement.order_by(WeighIn.recorded_at.desc(), WeighIn.id.desc()).limit(1)
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None:
        if resource_context:
            raise CapabilityError(
                "action_context_not_found",
                "La medición contextual no está disponible para esta cuenta.",
                404,
            )
        return {
            "needs_input": True,
            "resolution_code": "body_measurement_not_found",
        }
    return {
        "resource_type": "body_stat",
        "public_id": row.public_id,
        "base_revision": row.revision,
        "needs_input": not any(
            name in _payload and _payload.get(name) not in (None, "")
            for name in BODY_FIELDS
            if name not in METADATA_FIELDS
        ),
        "argument_defaults": {
            "weight": format(row.weight_kg, "f") if row.weight_kg is not None else None,
            "unit": "kg",
            "recorded_at": aware_iso(row.recorded_at),
        },
        "original": {
            "weight": format(row.weight_kg, "f") if row.weight_kg is not None else None,
            "unit": "kg",
            "recorded_at": aware_iso(row.recorded_at),
            "body_fat_percent": (
                format(row.body_fat_percentage, "f")
                if row.body_fat_percentage is not None
                else None
            ),
            "muscle_mass_kg": (
                format(row.muscle_mass_kg, "f")
                if row.muscle_mass_kg is not None
                else None
            ),
            "water_percent": (
                format(row.water_percentage, "f")
                if row.water_percentage is not None
                else None
            ),
            "visceral_fat": (
                format(row.visceral_fat, "f") if row.visceral_fat is not None else None
            ),
            "bmr_kcal": format(row.bmr_kcal, "f") if row.bmr_kcal is not None else None,
            "bmi": format(row.bmi, "f") if row.bmi is not None else None,
            "notes": row.notes,
        },
    }


def _preview(_user, payload: dict, context) -> dict:
    labels = {
        "weight": "Peso",
        "unit": "Unidad",
        "recorded_at": "Fecha y hora",
        "body_fat_percent": "Grasa corporal (%)",
        "muscle_mass_kg": "Masa muscular (kg)",
        "water_percent": "Agua corporal (%)",
        "visceral_fat": "Grasa visceral",
        "bmr_kcal": "BMR (kcal)",
        "bmi": "IMC",
        "notes": "Notas",
    }
    fields = [
        preview_field(
            name,
            label,
            payload.get(name),
            required=name in {"weight", "unit"},
            options=("kg", "lb") if name == "unit" else (),
        )
        for name, label in labels.items()
    ]
    return {"fields": fields, "original": context.get("original")}


def apply_body_create(user, draft, payload: dict, _context, now) -> ActionApplyResult:
    document = {"weight": payload["weight"], "unit": payload["unit"]}
    for field_name in BODY_FIELDS:
        if field_name in {"weight", "unit", *METADATA_FIELDS}:
            continue
        if field_name in payload:
            document[field_name] = payload[field_name]
    document.update(
        {
            "recorded_at": payload.get("recorded_at") or now.isoformat().replace("+00:00", "Z"),
            "source": "manual",
            "client_event_id": idempotency_uuid(draft.public_id, "body"),
        }
    )
    row = create_body_stat(user.id, document)
    return ActionApplyResult("body_stat", (row.public_id,))


def apply_body_correct(user, _draft, payload: dict, context, _now) -> ActionApplyResult:
    document = {
        key: value
        for key, value in payload.items()
        if key not in METADATA_FIELDS and key != "recorded_at"
    }
    if "recorded_at" in payload:
        document["recorded_at"] = payload["recorded_at"]
    document["base_revision"] = context.get("base_revision")
    row = patch_body_stat(user.id, context.get("public_id"), document)
    return ActionApplyResult("body_stat", (row.public_id,))


BODY_CREATE = ActionCapability(
    action_id="body.measurement.create",
    domain="body",
    entity="body_measurement",
    operation="create",
    label="Registrar medición",
    description="Prepara peso y composición corporal reportados por el usuario.",
    supported_fields=BODY_FIELDS,
    required_fields=("weight", "unit"),
    optional_fields=tuple(field for field in BODY_FIELDS if field not in {"weight", "unit"}),
    input_schema=BODY_SCHEMA,
    apply_handler=apply_body_create,
    draft_type="body_measurement",
    normalizer=_normalize,
    previewer=_preview,
)

BODY_CORRECT = ActionCapability(
    action_id="body.measurement.correct",
    domain="body",
    entity="body_measurement",
    operation="correct",
    label="Corregir medición",
    description="Prepara una corrección owner-only sobre la última medición.",
    supported_fields=BODY_FIELDS,
    required_fields=("weight", "unit"),
    optional_fields=tuple(field for field in BODY_FIELDS if field not in {"weight", "unit"}),
    input_schema=BODY_SCHEMA,
    apply_handler=apply_body_correct,
    draft_type="body_measurement",
    normalizer=_normalize,
    owner_resolver=_latest_body_context,
    previewer=_preview,
    required_read_capabilities=("get_latest_body_measurement",),
    idempotency_policy="owner_revision",
)
