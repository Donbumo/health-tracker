from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import TrainingSession
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
from app.services.workout_sessions import (
    TrainingSessionError,
    build_completed_workout_document,
    create_manual_training_session,
    list_planned_days,
    resolve_session_planned_day,
    update_manual_training_session,
)


SET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["set_number", "planned_set_number", "weight_kg", "reps"],
    "properties": {
        "set_number": {"type": "integer", "minimum": 1},
        "planned_set_number": {"type": "integer", "minimum": 1},
        "weight_kg": {"type": ["string", "number"], "minimum": 0, "maximum": 2000},
        "reps": {"type": "integer", "minimum": 1, "maximum": 10000},
        "rir": {"type": ["string", "number", "null"]},
        "rpe": {"type": ["string", "number", "null"]},
        "rest_seconds": {"type": ["integer", "null"], "minimum": 0, "maximum": 86400},
        "notes": {"type": ["string", "null"], "maxLength": 2000},
    },
}
EXERCISE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["exercise_order", "planned_exercise_order", "name", "sets"],
    "properties": {
        "exercise_order": {"type": "integer", "minimum": 1},
        "planned_exercise_order": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "notes": {"type": ["string", "null"], "maxLength": 2000},
        "sets": {"type": "array", "minItems": 1, "maxItems": 100, "items": SET_SCHEMA},
    },
}
TRAINING_FIELDS = (
    "plan_name",
    "week_number",
    "day_number",
    "workout_name",
    "performed_at",
    "duration_seconds",
    "average_heart_rate_bpm",
    "calories_burned",
    "notes",
    "exercises",
    *METADATA_FIELDS,
)
TRAINING_SCHEMA = action_schema(
    {
        "plan_name": {"type": "string", "minLength": 1, "maxLength": 200},
        "week_number": {"type": "integer", "minimum": 1},
        "day_number": {"type": "integer", "minimum": 1, "maximum": 7},
        "workout_name": {"type": "string", "minLength": 1, "maxLength": 200},
        "performed_at": {"type": "string", "format": "date-time"},
        "duration_seconds": {"type": ["integer", "null"], "minimum": 1, "maximum": 604800},
        "average_heart_rate_bpm": {"type": ["integer", "null"], "minimum": 20, "maximum": 250},
        "calories_burned": {"type": ["string", "number", "null"]},
        "notes": {"type": ["string", "null"], "maxLength": 5000},
        "exercises": {"type": "array", "minItems": 1, "maxItems": 100, "items": EXERCISE_SCHEMA},
    }
)


def _normalize(_user, payload: dict) -> dict:
    clean = clean_optional_strings(
        payload, ("plan_name", "workout_name", "performed_at", "notes")
    )
    if clean.get("calories_burned") is not None:
        bounded_decimal(
            clean["calories_burned"],
            "calories_burned",
            Decimal("0"),
            Decimal("100000"),
        )
        clean["calories_burned"] = float(Decimal(str(clean["calories_burned"])))
    exercises = clean.get("exercises")
    if isinstance(exercises, list):
        normalized_exercises = []
        for raw_exercise in exercises:
            if not isinstance(raw_exercise, dict):
                normalized_exercises.append(raw_exercise)
                continue
            exercise = clean_optional_strings(raw_exercise, ("notes",))
            sets = exercise.get("sets")
            if isinstance(sets, list):
                normalized_sets = []
                for raw_set in sets:
                    if not isinstance(raw_set, dict):
                        normalized_sets.append(raw_set)
                        continue
                    item = clean_optional_strings(raw_set, ("rir", "rpe", "notes"))
                    for field_name, minimum, maximum in (
                        ("weight_kg", Decimal("0"), Decimal("2000")),
                        ("rir", Decimal("0"), Decimal("10")),
                        ("rpe", Decimal("1"), Decimal("10")),
                    ):
                        if item.get(field_name) is not None:
                            bounded_decimal(
                                item[field_name], field_name, minimum, maximum
                            )
                            item[field_name] = float(Decimal(str(item[field_name])))
                    normalized_sets.append(item)
                exercise["sets"] = normalized_sets
            normalized_exercises.append(exercise)
        clean["exercises"] = normalized_exercises
    return clean


def _matching_day(user, payload: dict):
    selectors = (payload.get("plan_name"), payload.get("week_number"), payload.get("day_number"))
    if any(value in (None, "") for value in selectors):
        return None
    plan_name = str(payload["plan_name"]).strip().casefold()
    workout_name = str(payload.get("workout_name") or "").strip().casefold()
    matches = [
        item
        for item in list_planned_days(user.id)
        if item.plan.name.strip().casefold() == plan_name
        and item.week.get("week_number") == payload["week_number"]
        and item.day.get("day_number") == payload["day_number"]
        and (not workout_name or item.day.get("name", "").strip().casefold() == workout_name)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _create_context(user, payload: dict, _resource_context=None) -> dict:
    planned = _matching_day(user, payload)
    if planned is None:
        return {
            "needs_input": True,
            "resolution_code": "training_plan_day_not_found",
        }
    return {
        "resource_type": "training_plan_day",
        "plan_public_id": planned.plan.public_id,
        "plan_version_public_id": planned.version.public_id,
        "week_number": planned.week["week_number"],
        "day_number": planned.day["day_number"],
        "label": planned.label,
    }


def _session_exercises(row: TrainingSession) -> list[dict]:
    result = []
    for exercise in row.exercises:
        sets = []
        for item in exercise.sets:
            values = {
                "set_number": item.set_number,
                "planned_set_number": item.planned_set_number,
                "weight_kg": format(item.weight_kg, "f"),
                "reps": item.reps,
            }
            for name in ("rir", "rpe", "rest_seconds", "notes"):
                value = getattr(item, name)
                if value is not None:
                    values[name] = format(value, "f") if isinstance(value, Decimal) else value
            sets.append(values)
        values = {
            "exercise_order": exercise.exercise_order,
            "planned_exercise_order": exercise.planned_exercise_order,
            "name": exercise.name,
            "sets": sets,
        }
        if exercise.notes:
            values["notes"] = exercise.notes
        result.append(values)
    return result


def _latest_session(user) -> TrainingSession:
    row = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == user.id, TrainingSession.deleted_at.is_(None))
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise CapabilityError(
            "training_session_not_found", "No hay una sesión propia que pueda corregirse.", 422
        )
    return row


def _correction_context(user, _payload: dict, resource_context=None) -> dict:
    if resource_context:
        if resource_context.get("resource_type") != "training_session":
            raise CapabilityError(
                "invalid_action_context", "El contexto no corresponde a un entrenamiento.", 403
            )
        row = db.session.execute(
            db.select(TrainingSession).where(
                TrainingSession.user_id == user.id,
                TrainingSession.public_id == resource_context.get("resource_public_id"),
                TrainingSession.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            raise CapabilityError(
                "action_context_not_found",
                "El entrenamiento contextual no está disponible para esta cuenta.",
                404,
            )
    else:
        try:
            row = _latest_session(user)
        except CapabilityError:
            return {
                "needs_input": True,
                "resolution_code": "training_session_not_found",
            }
    defaults = {
        "performed_at": aware_iso(row.performed_at),
        "duration_seconds": row.duration_seconds,
        "average_heart_rate_bpm": row.average_heart_rate_bpm,
        "calories_burned": (
            format(row.calories_burned, "f")
            if row.calories_burned is not None
            else None
        ),
        "notes": row.notes,
        "exercises": _session_exercises(row),
    }
    return {
        "resource_type": "training_session",
        "public_id": row.public_id,
        "base_revision": row.revision,
        "needs_input": not any(
            name in _payload and _payload.get(name) not in (None, "")
            for name in (
                "performed_at",
                "duration_seconds",
                "average_heart_rate_bpm",
                "calories_burned",
                "notes",
                "exercises",
            )
        ),
        "argument_defaults": {
            key: value for key, value in defaults.items() if value is not None
        },
        "plan_public_id": row.training_plan.public_id,
        "week_number": row.planned_week_number,
        "day_number": row.planned_day_number,
        "original": {
            "performed_at": aware_iso(row.performed_at),
            "duration_seconds": row.duration_seconds,
            "average_heart_rate_bpm": row.average_heart_rate_bpm,
            "calories_burned": (
                format(row.calories_burned, "f")
                if row.calories_burned is not None
                else None
            ),
            "notes": row.notes,
            "exercises": _session_exercises(row),
        },
    }


def _preview(_user, payload: dict, context) -> dict:
    fields = [
        preview_field("plan_name", "Rutina", payload.get("plan_name"), required="public_id" not in context),
        preview_field("week_number", "Semana", payload.get("week_number"), kind="number"),
        preview_field("day_number", "Día", payload.get("day_number"), kind="number"),
        preview_field("workout_name", "Entrenamiento", payload.get("workout_name")),
        preview_field("performed_at", "Fecha y hora", payload.get("performed_at"), required=True),
        preview_field("duration_seconds", "Duración (segundos)", payload.get("duration_seconds"), kind="number"),
        preview_field("average_heart_rate_bpm", "Frecuencia cardiaca media", payload.get("average_heart_rate_bpm"), kind="number"),
        preview_field("calories_burned", "Calorías", payload.get("calories_burned"), kind="number"),
        preview_field("notes", "Notas", payload.get("notes")),
        preview_field("exercises", "Ejercicios y series (JSON)", payload.get("exercises"), kind="json", required=True),
    ]
    return {"fields": fields, "original": context.get("original"), "context_label": context.get("label")}


def _parse_performed_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise CapabilityError("invalid_action_arguments", "performed_at no es válido.", 422) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CapabilityError("invalid_action_arguments", "performed_at requiere zona horaria.", 422)
    return parsed


def apply_training_create(user, draft, payload: dict, _context, _now) -> ActionApplyResult:
    planned = _matching_day(user, payload)
    if planned is None:
        raise CapabilityError("action_needs_input", "Selecciona rutina, semana y día.", 422)
    try:
        row, _duplicate = create_manual_training_session(
            user_id=user.id,
            planned_day=planned,
            performed_at=_parse_performed_at(payload["performed_at"]),
            exercises=payload["exercises"],
            duration_seconds=payload.get("duration_seconds"),
            average_heart_rate_bpm=payload.get("average_heart_rate_bpm"),
            calories_burned=payload.get("calories_burned"),
            notes=payload.get("notes"),
            client_submission_id=idempotency_uuid(draft.public_id, "training"),
            preferred_load_unit=user.preferred_load_unit,
        )
    except TrainingSessionError as error:
        raise CapabilityError("training_session_invalid", "La sesión no cumple el plan activo.", 422) from error
    return ActionApplyResult("training_session", (row.public_id,))


def apply_training_correct(user, _draft, payload: dict, context, _now) -> ActionApplyResult:
    row = db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.user_id == user.id,
            TrainingSession.public_id == context.get("public_id"),
            TrainingSession.deleted_at.is_(None),
        ).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise CapabilityError("training_session_not_found", "La sesión ya no está disponible.", 404)
    try:
        planned = resolve_session_planned_day(row, user.id)
    except TrainingSessionError as error:
        raise CapabilityError(
            "training_plan_day_not_found", "El día original del plan ya no está disponible.", 409
        ) from error
    if row.revision != context.get("base_revision"):
        try:
            from app.services.mobile_sync import canonical_hash

            intended = build_completed_workout_document(
                user_id=user.id,
                planned_day=planned,
                performed_at=_parse_performed_at(payload["performed_at"]),
                exercises=payload["exercises"],
                duration_seconds=payload.get("duration_seconds"),
                average_heart_rate_bpm=payload.get("average_heart_rate_bpm"),
                calories_burned=payload.get("calories_burned"),
                notes=payload.get("notes"),
                client_submission_id=row.client_submission_id,
            )
        except TrainingSessionError as error:
            raise CapabilityError(
                "training_session_invalid", "La corrección no cumple el plan activo.", 422
            ) from error
        if row.client_payload_sha256 == canonical_hash(intended):
            return ActionApplyResult("training_session", (row.public_id,))
        raise CapabilityError("revision_conflict", "La sesión cambió desde el preview.", 409)
    try:
        updated, _duplicate = update_manual_training_session(
            session=row,
            user_id=user.id,
            planned_day=planned,
            performed_at=_parse_performed_at(payload["performed_at"]),
            exercises=payload["exercises"],
            duration_seconds=payload.get("duration_seconds"),
            average_heart_rate_bpm=payload.get("average_heart_rate_bpm"),
            calories_burned=payload.get("calories_burned"),
            notes=payload.get("notes"),
            preferred_load_unit=user.preferred_load_unit,
        )
    except TrainingSessionError as error:
        raise CapabilityError("training_session_invalid", "La corrección no cumple el plan activo.", 422) from error
    return ActionApplyResult("training_session", (updated.public_id,))


TRAINING_CREATE = ActionCapability(
    action_id="training.session.create",
    domain="training",
    entity="training_session",
    operation="create",
    label="Registrar entrenamiento",
    description="Prepara una sesión ligada a un día de la rutina activa.",
    supported_fields=TRAINING_FIELDS,
    required_fields=("plan_name", "week_number", "day_number", "performed_at", "exercises"),
    optional_fields=tuple(
        field
        for field in TRAINING_FIELDS
        if field not in {"plan_name", "week_number", "day_number", "performed_at", "exercises"}
    ),
    input_schema=TRAINING_SCHEMA,
    apply_handler=apply_training_create,
    normalizer=_normalize,
    owner_resolver=_create_context,
    previewer=_preview,
)

TRAINING_CORRECT = ActionCapability(
    action_id="training.session.correct",
    domain="training",
    entity="training_session",
    operation="correct",
    label="Corregir entrenamiento",
    description="Prepara una corrección owner-only de la última sesión.",
    supported_fields=TRAINING_FIELDS,
    required_fields=("performed_at", "exercises"),
    optional_fields=tuple(field for field in TRAINING_FIELDS if field not in {"performed_at", "exercises"}),
    input_schema=TRAINING_SCHEMA,
    apply_handler=apply_training_correct,
    normalizer=_normalize,
    owner_resolver=_correction_context,
    previewer=_preview,
    required_read_capabilities=("get_training_history",),
    idempotency_policy="owner_revision",
)
