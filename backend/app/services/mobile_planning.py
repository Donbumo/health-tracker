import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Exercise,
    ExerciseAlias,
    PlannedWorkout,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingPlanWorkout,
)
from app.services.mobile_sync import (
    MobileSyncError,
    record_sync_change,
    rfc3339,
    serialize_planned_workout,
    validate_timezone,
)
from app.services.training_plans import serialize_training_plan
from app.services.validation import validate_json_document
from app.services.workout_loads import (
    MODE_COMPONENTS,
    WorkoutLoadError,
    calculate_workout_load,
    validate_load_details,
)


LOAD_MODES = {
    "direct_total",
    "per_side",
    "bar_plus_per_side",
    "machine_initial_total",
    "machine_initial_per_side",
    "machine_external_per_side_initial_total",
    "selector_stack",
    "dumbbell_each",
    "bodyweight",
    "bodyweight_plus",
    "assistance",
    "duration_distance",
}
MAX_WORKOUTS = 728
MAX_EXERCISES = 100
MAX_SETS = 100


def _uuid(value: str, label: str = "ID") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_id", f"{label} no es válido.") from error


def _text(value, *, field: str, maximum: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    result = value.strip()
    if (required and not result) or len(result) > maximum:
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return result or None


def _integer(value, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return value


def _decimal(value, *, field: str, minimum=None, maximum=None) -> str:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_request", f"{field} no es válido.") from error
    if not result.is_finite() or (minimum is not None and result < Decimal(str(minimum))) or (
        maximum is not None and result > Decimal(str(maximum))
    ):
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return format(result.normalize(), "f")


def _owned_plan(user_id: int, public_id: str, *, lock: bool = False) -> TrainingPlan:
    public_id = _uuid(public_id, "El ID de rutina")
    statement = (
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == user_id, TrainingPlan.public_id == public_id)
        .options(selectinload(TrainingPlan.workouts))
    )
    if lock:
        statement = statement.with_for_update()
    plan = db.session.execute(statement).scalar_one_or_none()
    if plan is None:
        raise MobileSyncError("not_found", "Rutina no encontrada.", 404)
    return plan


def _owned_workout(user_id: int, public_id: str, *, lock: bool = False) -> TrainingPlanWorkout:
    public_id = _uuid(public_id, "El ID de entrenamiento")
    statement = db.select(TrainingPlanWorkout).where(
        TrainingPlanWorkout.user_id == user_id,
        TrainingPlanWorkout.public_id == public_id,
    )
    if lock:
        statement = statement.with_for_update()
    workout = db.session.execute(statement).scalar_one_or_none()
    if workout is None:
        raise MobileSyncError("not_found", "Entrenamiento no encontrado.", 404)
    return workout


def _check_revision(current: int, supplied, *, resource: str) -> None:
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise MobileSyncError("invalid_request", "Se requiere base_revision.")
    if supplied != current:
        raise MobileSyncError(
            "revision_conflict",
            f"{resource} cambió en el servidor.",
            409,
            {
                "server_revision": current,
                "conflict_code": "stale_revision",
                "resolution_options": ["keep_remote", "retry_local_copy"],
            },
        )


def _validate_set(value: dict, position: int) -> dict:
    if not isinstance(value, dict):
        raise MobileSyncError("invalid_request", "La prescripción no es válida.")
    allowed = {
        "id",
        "set_number",
        "reps",
        "reps_min",
        "reps_max",
        "weight_kg",
        "load_value",
        "load_unit",
        "load_mode",
        "load_components",
        "load_details",
        "rir",
        "rpe",
        "rest_seconds",
        "duration_seconds",
        "distance_m",
        "notes",
    }
    if set(value) - allowed:
        raise MobileSyncError("invalid_request", "La prescripción contiene campos desconocidos.")
    result = {
        "id": _uuid(value.get("id") or str(uuid.uuid4()), "El ID de serie"),
        "set_number": position,
    }
    for field in ("reps", "reps_min", "reps_max"):
        if value.get(field) is not None:
            result[field] = _integer(value[field], field=field, minimum=1, maximum=100000)
    if ("reps_min" in result) != ("reps_max" in result) or result.get("reps_min", 0) > result.get("reps_max", 100000):
        raise MobileSyncError("invalid_request", "El rango de repeticiones no es válido.")
    if value.get("duration_seconds") is not None:
        result["duration_seconds"] = _integer(
            value["duration_seconds"], field="duration_seconds", minimum=1, maximum=86400
        )
    if value.get("rest_seconds") is not None:
        result["rest_seconds"] = _integer(
            value["rest_seconds"], field="rest_seconds", minimum=0, maximum=86400
        )
    if value.get("distance_m") is not None:
        result["distance_m"] = _decimal(value["distance_m"], field="distance_m", minimum="0.001")
    for field, maximum in (("rir", 20), ("rpe", 10)):
        if value.get(field) is not None:
            result[field] = _decimal(value[field], field=field, minimum=0, maximum=maximum)
    mode = value.get("load_mode", "direct_total")
    if mode not in LOAD_MODES:
        raise MobileSyncError("invalid_request", "load_mode no es válido.")
    result["load_mode"] = mode
    unit = value.get("load_unit", "kg")
    if unit not in {"kg", "lb"}:
        raise MobileSyncError("invalid_request", "load_unit no es válido.")
    result["load_unit"] = unit
    for field in ("weight_kg", "load_value"):
        if value.get(field) is not None:
            result[field] = _decimal(value[field], field=field, minimum=0)
    components = value.get("load_components")
    details = value.get("load_details")
    if components is not None and details is not None:
        raise MobileSyncError("invalid_request", "Usa componentes o detalle de carga, no ambos.")
    try:
        if details is not None:
            if not isinstance(details, dict):
                raise WorkoutLoadError("load_details must be an object")
            normalized = validate_load_details(value.get("weight_kg"), details)
            result["load_details"] = normalized
            result["weight_kg"] = _decimal(value.get("weight_kg"), field="weight_kg", minimum=0)
        elif components is not None:
            if not isinstance(components, dict) or len(components) > 16:
                raise WorkoutLoadError("load_components must be an object")
            calculated = calculate_workout_load(mode, unit, components)
            result["load_details"] = calculated.details
            result["weight_kg"] = format(calculated.weight_kg.normalize(), "f")
        elif value.get("load_value") is not None and len(MODE_COMPONENTS[mode]) == 1:
            calculated = calculate_workout_load(
                mode, unit, {MODE_COMPONENTS[mode][0]: value["load_value"]}
            )
            result["load_details"] = calculated.details
            result["weight_kg"] = format(calculated.weight_kg.normalize(), "f")
        elif mode == "duration_distance" and {
            "duration_seconds",
            "distance_m",
        }.issubset(result):
            calculated = calculate_workout_load(
                mode,
                unit,
                {
                    "duration_seconds": result["duration_seconds"],
                    "distance_meters": result["distance_m"],
                },
            )
            result["load_details"] = calculated.details
            result["weight_kg"] = "0"
    except WorkoutLoadError as error:
        raise MobileSyncError("invalid_request", "La prescripción de carga no es válida.") from error
    result["notes"] = _text(value.get("notes"), field="notes", maximum=2000)
    has_reps = any(field in result for field in ("reps", "reps_min"))
    has_timed = "duration_seconds" in result or "distance_m" in result
    if mode == "duration_distance" and not has_timed:
        raise MobileSyncError("invalid_request", "Tiempo o distancia son obligatorios para este modo.")
    if mode != "duration_distance" and not has_reps and not has_timed:
        raise MobileSyncError("invalid_request", "La serie requiere repeticiones, tiempo o distancia.")
    return {key: item for key, item in result.items() if item is not None}


def validate_exercises(values) -> list[dict]:
    if not isinstance(values, list) or len(values) > MAX_EXERCISES:
        raise MobileSyncError("invalid_request", "La lista de ejercicios no es válida.")
    result = []
    seen = set()
    for position, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            raise MobileSyncError("invalid_request", "El ejercicio no es válido.")
        allowed = {"id", "exercise_id", "exercise_order", "name", "notes", "sets"}
        if set(value) - allowed:
            raise MobileSyncError("invalid_request", "El ejercicio contiene campos desconocidos.")
        item_id = _uuid(value.get("id") or str(uuid.uuid4()), "El ID de prescripción")
        if item_id in seen:
            raise MobileSyncError("invalid_request", "El ejercicio está duplicado.")
        seen.add(item_id)
        exercise_id = value.get("exercise_id")
        if exercise_id is not None:
            exercise_id = _uuid(exercise_id, "El ID de ejercicio")
        sets = value.get("sets", [])
        if not isinstance(sets, list) or not 1 <= len(sets) <= MAX_SETS:
            raise MobileSyncError("invalid_request", "Las series no son válidas.")
        result.append(
            {key: item for key, item in {
                "id": item_id,
                "exercise_id": exercise_id,
                "exercise_order": position,
                "name": _text(value.get("name"), field="name", maximum=200, required=True),
                "notes": _text(value.get("notes"), field="notes", maximum=2000),
                "sets": [_validate_set(item, index) for index, item in enumerate(sets, start=1)],
            }.items() if item is not None}
        )
    return result


def _version_document(plan: TrainingPlan, workouts: list[TrainingPlanWorkout]) -> dict:
    weeks = []
    for week_index in range(0, len(workouts), 7):
        days = []
        for day_number, workout in enumerate(workouts[week_index : week_index + 7], start=1):
            days.append(
                {
                    "day_number": day_number,
                    "name": workout.name,
                    **({"notes": workout.notes} if workout.notes else {}),
                    "exercises": workout.exercises_json,
                }
            )
        weeks.append({"week_number": len(weeks) + 1, "days": days})
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": plan.user_id,
        "source_type": "manual_generated",
        "data": {
            "name": plan.name,
            **({"description": plan.description} if plan.description else {}),
            "weeks": weeks,
        },
    }


def _publish_version(plan: TrainingPlan) -> TrainingPlanVersion | None:
    workouts = db.session.execute(
        db.select(TrainingPlanWorkout)
        .where(
            TrainingPlanWorkout.user_id == plan.user_id,
            TrainingPlanWorkout.training_plan_id == plan.id,
        )
        .order_by(TrainingPlanWorkout.position)
    ).scalars().all()
    if not workouts:
        return None
    document = _version_document(plan, workouts)
    validate_json_document(document, "training_plan")
    digest = hashlib.sha256(serialize_training_plan(document)).hexdigest()
    duplicate = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == plan.user_id,
            TrainingPlanVersion.sha256 == digest,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        plan.active_version_number = duplicate.version_number
        return duplicate
    latest = db.session.execute(
        db.select(db.func.max(TrainingPlanVersion.version_number)).where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == plan.user_id,
        )
    ).scalar_one()
    version = TrainingPlanVersion(
        user_id=plan.user_id,
        training_plan_id=plan.id,
        version_number=(latest or 0) + 1,
        created_by_user_id=plan.user_id,
        change_reason="Edición desde Android",
        schema_version="1.0",
        sha256=digest,
        content=document,
    )
    db.session.add(version)
    db.session.flush()
    plan.active_version_number = version.version_number
    return version


def _active_version(plan: TrainingPlan) -> TrainingPlanVersion | None:
    return db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.user_id == plan.user_id,
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.version_number == plan.active_version_number,
        )
    ).scalar_one_or_none()


def _scheduled_snapshot(
    plan: TrainingPlan,
    version: TrainingPlanVersion,
    workout: TrainingPlanWorkout,
) -> dict:
    week_number = ((workout.position - 1) // 7) + 1
    day_number = ((workout.position - 1) % 7) + 1
    return {
        "schema_version": "1.0",
        "plan_id": plan.public_id,
        "plan_version_id": version.public_id,
        "plan_version": version.version_number,
        "week_number": week_number,
        "day_number": day_number,
        "workout_id": workout.public_id,
        "day": {
            "day_number": day_number,
            "name": workout.name,
            "exercises": json.loads(json.dumps(workout.exercises_json)),
        },
    }


def _refresh_unstarted_schedules(
    plan: TrainingPlan,
    version: TrainingPlanVersion | None,
    device_id: int | None,
) -> None:
    if version is None:
        return
    workouts = {item.public_id: item for item in plan.workouts}
    records = db.session.execute(
        db.select(PlannedWorkout).where(
            PlannedWorkout.user_id == plan.user_id,
            PlannedWorkout.training_plan_id == plan.id,
            PlannedWorkout.deleted_at.is_(None),
            PlannedWorkout.status == "planned",
        )
    ).scalars().all()
    for record in records:
        workout_id = (record.payload_snapshot_json or {}).get("workout_id")
        workout = workouts.get(workout_id)
        if workout is None:
            continue
        record.training_plan = plan
        record.training_plan_version = version
        record.source_version = version.version_number
        record.title_snapshot = workout.name
        record.payload_snapshot_json = _scheduled_snapshot(plan, version, workout)
        record.revision += 1
        record.updated_at = datetime.now(timezone.utc)
        record.last_modified_by_device_id = device_id
        db.session.flush()
        record_sync_change(
            user_id=record.user_id,
            entity_type="planned_workout",
            entity_public_id=record.public_id,
            operation="upsert",
            revision=record.revision,
            payload=serialize_planned_workout(record),
            device_id=device_id,
        )


def serialize_workout(workout: TrainingPlanWorkout) -> dict:
    return {
        "public_id": workout.public_id,
        "name": workout.name,
        "notes": workout.notes,
        "position": workout.position,
        "exercises": workout.exercises_json,
        "estimated_duration_seconds": sum(
            (item.get("rest_seconds") or 0) + (item.get("duration_seconds") or 0)
            for exercise in workout.exercises_json
            for item in exercise["sets"]
        )
        or None,
        "revision": workout.revision,
        "created_at": rfc3339(workout.created_at),
        "updated_at": rfc3339(workout.updated_at),
    }


_VERSION_UNSET = object()


def serialize_plan(
    plan: TrainingPlan,
    *,
    include_workouts: bool = True,
    version: TrainingPlanVersion | None | object = _VERSION_UNSET,
) -> dict:
    if version is _VERSION_UNSET:
        version = _active_version(plan)
    workouts = sorted(plan.workouts, key=lambda item: item.position)
    return {
        "public_id": plan.public_id,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "revision": plan.revision,
        "active_version_id": version.public_id if version else None,
        "active_version": version.version_number if version else None,
        "workout_count": len(workouts),
        "workouts": [serialize_workout(item) for item in workouts] if include_workouts else None,
        "created_at": rfc3339(plan.created_at),
        "updated_at": rfc3339(plan.updated_at),
        "archived_at": rfc3339(plan.archived_at),
    }


def _record_plan(plan: TrainingPlan, device_id: int | None) -> None:
    record_sync_change(
        user_id=plan.user_id,
        entity_type="training_plan",
        entity_public_id=plan.public_id,
        operation="upsert",
        revision=plan.revision,
        payload=serialize_plan(plan),
        device_id=device_id,
    )


def list_plans(user_id: int, status: str | None = "active") -> list[dict]:
    statement = (
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == user_id)
        .options(selectinload(TrainingPlan.workouts))
        .order_by(TrainingPlan.updated_at.desc(), TrainingPlan.public_id)
    )
    if status in {"active", "archived"}:
        statement = statement.where(TrainingPlan.status == status)
    elif status not in {None, "all"}:
        raise MobileSyncError("invalid_filter", "El estado solicitado no es válido.")
    plans = db.session.execute(statement).scalars().all()
    plan_ids = [item.id for item in plans]
    versions = {}
    if plan_ids:
        versions = {
            (item.training_plan_id, item.version_number): item
            for item in db.session.execute(
                db.select(TrainingPlanVersion)
                .join(TrainingPlan, TrainingPlan.id == TrainingPlanVersion.training_plan_id)
                .where(
                    TrainingPlanVersion.user_id == user_id,
                    TrainingPlanVersion.training_plan_id.in_(plan_ids),
                    TrainingPlanVersion.version_number == TrainingPlan.active_version_number,
                )
            ).scalars()
        }
    return [
        serialize_plan(
            item,
            include_workouts=False,
            version=versions.get((item.id, item.active_version_number)),
        )
        for item in plans
    ]


def plan_detail(user_id: int, public_id: str) -> dict:
    return serialize_plan(_owned_plan(user_id, public_id))


def create_plan(*, user_id: int, payload: dict, device_id: int | None) -> TrainingPlan:
    if set(payload) - {"public_id", "name", "description"}:
        raise MobileSyncError("invalid_request", "La rutina contiene campos desconocidos.")
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()), "El ID de rutina")
    if db.session.execute(db.select(TrainingPlan).where(TrainingPlan.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    plan = TrainingPlan(
        public_id=public_id,
        user_id=user_id,
        name=_text(payload.get("name"), field="name", maximum=200, required=True),
        description=_text(payload.get("description"), field="description", maximum=5000),
    )
    db.session.add(plan)
    db.session.flush()
    _record_plan(plan, device_id)
    return plan


def patch_plan(*, user_id: int, public_id: str, payload: dict, device_id: int | None) -> TrainingPlan:
    allowed = {"base_revision", "name", "description", "status", "workout_order"}
    if set(payload) - allowed or "base_revision" not in payload:
        raise MobileSyncError("invalid_request", "La edición de rutina no es válida.")
    plan = _owned_plan(user_id, public_id, lock=True)
    _check_revision(plan.revision, payload["base_revision"], resource="La rutina")
    if plan.status == "archived" and payload.get("status") != "active":
        raise MobileSyncError("resource_archived", "La rutina está archivada.", 409)
    if "name" in payload:
        plan.name = _text(payload["name"], field="name", maximum=200, required=True)
    if "description" in payload:
        plan.description = _text(payload["description"], field="description", maximum=5000)
    if "status" in payload:
        if payload["status"] not in {"active", "archived"}:
            raise MobileSyncError("invalid_request", "El estado no es válido.")
        if payload["status"] == "archived" and plan.status != "archived":
            active_schedules = db.session.execute(
                db.select(db.func.count(PlannedWorkout.id)).where(
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.training_plan_id == plan.id,
                    PlannedWorkout.deleted_at.is_(None),
                    PlannedWorkout.status.in_(("planned", "in_progress")),
                )
            ).scalar_one()
            if active_schedules:
                raise MobileSyncError(
                    "active_schedules",
                    "La rutina tiene programaciones activas; cancélalas antes de archivarla.",
                    409,
                    {"active_schedule_count": active_schedules},
                )
        plan.status = payload["status"]
        plan.archived_at = datetime.now(timezone.utc) if plan.status == "archived" else None
    if "workout_order" in payload:
        order = payload["workout_order"]
        current = {item.public_id: item for item in plan.workouts}
        if not isinstance(order, list) or len(order) != len(current):
            raise MobileSyncError("invalid_request", "El orden no es válido.")
        normalized = [_uuid(item, "El ID de entrenamiento") for item in order]
        if set(normalized) != set(current):
            raise MobileSyncError("invalid_request", "El orden no es válido.")
        for workout in current.values():
            workout.position += 1000
        db.session.flush()
        for position, item in enumerate(normalized, start=1):
            current[item].position = position
            current[item].revision += 1
            current[item].updated_at = datetime.now(timezone.utc)
    plan.revision += 1
    plan.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    version = _publish_version(plan)
    db.session.flush()
    _refresh_unstarted_schedules(plan, version, device_id)
    _record_plan(plan, device_id)
    return plan


def duplicate_plan(*, user_id: int, public_id: str, payload: dict, device_id: int | None) -> TrainingPlan:
    if set(payload) - {"public_id", "name"}:
        raise MobileSyncError("invalid_request", "La duplicación no es válida.")
    source = _owned_plan(user_id, public_id)
    target = TrainingPlan(
        public_id=_uuid(payload.get("public_id") or str(uuid.uuid4()), "El ID de rutina"),
        user_id=user_id,
        name=_text(payload.get("name") or f"{source.name} (copia)", field="name", maximum=200, required=True),
        description=source.description,
    )
    if db.session.execute(db.select(TrainingPlan).where(TrainingPlan.public_id == target.public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    db.session.add(target)
    db.session.flush()
    for source_workout in sorted(source.workouts, key=lambda item: item.position):
        db.session.add(
            TrainingPlanWorkout(
                public_id=str(uuid.uuid4()),
                user_id=user_id,
                training_plan=target,
                name=source_workout.name,
                notes=source_workout.notes,
                position=source_workout.position,
                exercises_json=json.loads(json.dumps(source_workout.exercises_json)),
            )
        )
    db.session.flush()
    _publish_version(target)
    db.session.refresh(target)
    _record_plan(target, device_id)
    return target


def create_workout(*, user_id: int, plan_public_id: str, payload: dict, device_id: int | None) -> TrainingPlanWorkout:
    if set(payload) - {"public_id", "name", "notes", "exercises", "base_revision"}:
        raise MobileSyncError("invalid_request", "El entrenamiento contiene campos desconocidos.")
    plan = _owned_plan(user_id, plan_public_id, lock=True)
    _check_revision(plan.revision, payload.get("base_revision"), resource="La rutina")
    if plan.status != "active":
        raise MobileSyncError("resource_archived", "La rutina está archivada.", 409)
    if len(plan.workouts) >= MAX_WORKOUTS:
        raise MobileSyncError("limit_exceeded", "La rutina alcanzó el máximo de entrenamientos.", 413)
    public_id = _uuid(payload.get("public_id") or str(uuid.uuid4()), "El ID de entrenamiento")
    if db.session.execute(db.select(TrainingPlanWorkout).where(TrainingPlanWorkout.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    workout = TrainingPlanWorkout(
        public_id=public_id,
        user_id=user_id,
        training_plan=plan,
        name=_text(payload.get("name"), field="name", maximum=200, required=True),
        notes=_text(payload.get("notes"), field="notes", maximum=5000),
        position=len(plan.workouts) + 1,
        exercises_json=validate_exercises(payload.get("exercises", [])),
    )
    db.session.add(workout)
    plan.revision += 1
    plan.updated_at = datetime.now(timezone.utc)
    db.session.flush()
    version = _publish_version(plan)
    db.session.flush()
    _refresh_unstarted_schedules(plan, version, device_id)
    _record_plan(plan, device_id)
    return workout


def patch_workout(*, user_id: int, public_id: str, payload: dict, device_id: int | None) -> TrainingPlanWorkout:
    allowed = {"base_revision", "name", "notes", "exercises"}
    if set(payload) - allowed or "base_revision" not in payload:
        raise MobileSyncError("invalid_request", "La edición no es válida.")
    workout = _owned_workout(user_id, public_id, lock=True)
    plan = _owned_plan(user_id, workout.training_plan.public_id, lock=True)
    _check_revision(workout.revision, payload["base_revision"], resource="El entrenamiento")
    if plan.status != "active":
        raise MobileSyncError("resource_archived", "La rutina está archivada.", 409)
    if "name" in payload:
        workout.name = _text(payload["name"], field="name", maximum=200, required=True)
    if "notes" in payload:
        workout.notes = _text(payload["notes"], field="notes", maximum=5000)
    if "exercises" in payload:
        workout.exercises_json = validate_exercises(payload["exercises"])
    workout.revision += 1
    workout.updated_at = datetime.now(timezone.utc)
    plan.revision += 1
    plan.updated_at = workout.updated_at
    db.session.flush()
    version = _publish_version(plan)
    db.session.flush()
    _refresh_unstarted_schedules(plan, version, device_id)
    _record_plan(plan, device_id)
    return workout


def duplicate_workout(*, user_id: int, public_id: str, payload: dict, device_id: int | None) -> TrainingPlanWorkout:
    source = _owned_workout(user_id, public_id)
    plan = _owned_plan(user_id, source.training_plan.public_id, lock=True)
    _check_revision(plan.revision, payload.get("base_revision"), resource="La rutina")
    return create_workout(
        user_id=user_id,
        plan_public_id=plan.public_id,
        payload={
            "public_id": payload.get("public_id"),
            "name": payload.get("name") or f"{source.name} (copia)",
            "notes": source.notes,
            "exercises": json.loads(json.dumps(source.exercises_json)),
            "base_revision": plan.revision,
        },
        device_id=device_id,
    )


def schedule_workout(
    *, user_id: int, public_id: str, payload: dict, device_id: int | None
) -> PlannedWorkout:
    if set(payload) - {"public_id", "scheduled_for_date", "timezone"}:
        raise MobileSyncError("invalid_request", "La programación no es válida.")
    workout = _owned_workout(user_id, public_id)
    plan = _owned_plan(user_id, workout.training_plan.public_id)
    if plan.status != "active":
        raise MobileSyncError("resource_archived", "La rutina está archivada.", 409)
    version = _active_version(plan)
    if version is None:
        raise MobileSyncError("conflict", "La rutina no tiene una versión ejecutable.", 409)
    validate_timezone(payload.get("timezone"))
    try:
        scheduled = date.fromisoformat(payload.get("scheduled_for_date"))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_date", "scheduled_for_date debe usar YYYY-MM-DD.") from error
    planned_id = _uuid(payload.get("public_id") or str(uuid.uuid4()), "El ID de programación")
    existing = db.session.execute(db.select(PlannedWorkout).where(PlannedWorkout.public_id == planned_id)).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise MobileSyncError("not_found", "Programación no encontrada.", 404)
        raise MobileSyncError("conflict", "El ID ya existe.", 409)
    snapshot = _scheduled_snapshot(plan, version, workout)
    record = PlannedWorkout(
        public_id=planned_id,
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        scheduled_for_date=scheduled,
        timezone=payload["timezone"],
        title_snapshot=workout.name,
        payload_snapshot_json=snapshot,
        source_version=version.version_number,
        last_modified_by_device_id=device_id,
    )
    db.session.add(record)
    db.session.flush()
    record_sync_change(
        user_id=user_id,
        entity_type="planned_workout",
        entity_public_id=record.public_id,
        operation="upsert",
        revision=record.revision,
        payload=serialize_planned_workout(record),
        device_id=device_id,
    )
    return record


def _catalog_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="exercise-catalog-v1")


def exercise_catalog(*, user_id: int, search: str | None, limit: int, cursor: str | None) -> dict:
    if not 1 <= limit <= 100:
        raise MobileSyncError("invalid_limit", "El límite no es válido.")
    query = _text(search, field="search", maximum=200) if search is not None else None
    statement = db.select(Exercise).where(Exercise.user_id == user_id).options(
        selectinload(Exercise.load_profile), selectinload(Exercise.aliases)
    )
    if query:
        normalized_query = query.casefold()
        statement = statement.where(
            db.or_(
                Exercise.normalized_name.contains(normalized_query),
                Exercise.aliases.any(ExerciseAlias.normalized_name.contains(normalized_query)),
            )
        )
    if cursor:
        try:
            after_name, after_id = _catalog_serializer().loads(cursor)
            after_id = _uuid(after_id)
        except (BadData, TypeError, ValueError) as error:
            raise MobileSyncError("invalid_cursor", "El cursor no es válido.") from error
        statement = statement.where(
            db.or_(
                Exercise.normalized_name > after_name,
                db.and_(Exercise.normalized_name == after_name, Exercise.public_id > after_id),
            )
        )
    rows = db.session.execute(statement.order_by(Exercise.normalized_name, Exercise.public_id).limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "public_id": item.public_id,
                "name": item.canonical_name,
                "aliases": [alias.alias_name for alias in item.aliases],
                "custom": True,
                "archived": False,
                "selectable": True,
                "muscle_group": None,
                "equipment": None,
                "preferred_load_mode": item.load_profile.load_mode if item.load_profile else None,
                "preferred_unit": item.load_profile.preferred_unit if item.load_profile else None,
            }
            for item in rows
        ],
        "next_cursor": (
            _catalog_serializer().dumps([rows[-1].normalized_name, rows[-1].public_id])
            if has_more and rows
            else None
        ),
        "has_more": has_more,
        "available_filters": {"muscle_group": False, "equipment": False},
    }
