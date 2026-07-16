import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ApiDevice,
    DeviceSyncState,
    IdempotencyRecord,
    PlannedWorkout,
    SyncChange,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
)
from app.services.validation import validate_json_document
from app.services.validation import JsonSchemaValidationError


PLANNED_STATUSES = {"planned", "in_progress", "completed", "skipped", "cancelled"}
SYNC_ENTITY_TYPES = {"planned_workout", "completed_workout"}


class MobileSyncError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rfc3339(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_rfc3339(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_datetime", f"{field} debe ser RFC3339.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MobileSyncError("invalid_datetime", f"{field} debe incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (TypeError, ZoneInfoNotFoundError) as error:
        raise MobileSyncError("invalid_timezone", "La zona horaria IANA no es válida.") from error
    return value


def _owned_plan(user_id: int, public_id: str) -> TrainingPlan:
    plan = db.session.execute(
        db.select(TrainingPlan).where(
            TrainingPlan.user_id == user_id, TrainingPlan.public_id == public_id
        )
    ).scalar_one_or_none()
    if plan is None:
        raise MobileSyncError("not_found", "Rutina no encontrada.", 404)
    return plan


def _owned_version(
    user_id: int, plan: TrainingPlan, public_id: str | None
) -> TrainingPlanVersion:
    statement = db.select(TrainingPlanVersion).where(
        TrainingPlanVersion.user_id == user_id,
        TrainingPlanVersion.training_plan_id == plan.id,
    )
    if public_id:
        statement = statement.where(TrainingPlanVersion.public_id == public_id)
    else:
        statement = statement.where(
            TrainingPlanVersion.version_number == plan.active_version_number
        )
    version = db.session.execute(statement).scalar_one_or_none()
    if version is None:
        raise MobileSyncError("not_found", "Versión de rutina no encontrada.", 404)
    return version


def _day_snapshot(
    version: TrainingPlanVersion, week_number: int, day_number: int
) -> dict:
    for week in version.content["data"]["weeks"]:
        if week["week_number"] != week_number:
            continue
        for day in week["days"]:
            if day["day_number"] == day_number:
                return {
                    "schema_version": "1.0",
                    "plan_id": version.training_plan.public_id,
                    "plan_version_id": version.public_id,
                    "plan_version": version.version_number,
                    "week_number": week_number,
                    "day_number": day_number,
                    "day": json.loads(json.dumps(day)),
                }
    raise MobileSyncError("invalid_plan_day", "El día no existe en esa versión.")


def serialize_planned_workout(record: PlannedWorkout) -> dict:
    return {
        "schema_version": "1.0",
        "id": record.public_id,
        "training_plan_id": record.training_plan.public_id,
        "training_plan_version_id": record.training_plan_version.public_id,
        "scheduled_for_date": record.scheduled_for_date.isoformat(),
        "timezone": record.timezone,
        "status": record.status,
        "title": record.title_snapshot,
        "snapshot": record.payload_snapshot_json,
        "source_version": record.source_version,
        "revision": record.revision,
        "created_at": rfc3339(record.created_at),
        "updated_at": rfc3339(record.updated_at),
        "completed_at": rfc3339(record.completed_at),
        "cancelled_at": rfc3339(record.cancelled_at),
        "deleted": record.deleted_at is not None,
    }


def serialize_completed_workout(record: TrainingSession) -> dict:
    return {
        "schema_version": "1.0",
        "id": record.public_id,
        "client_event_id": record.client_event_id,
        "planned_workout_id": (
            record.planned_workout.public_id if record.planned_workout else None
        ),
        "training_plan_id": record.training_plan.public_id,
        "training_plan_version_id": record.training_plan_version.public_id,
        "started_at": rfc3339(record.started_at or record.performed_at),
        "completed_at": rfc3339(record.completed_at or record.performed_at),
        "timezone": record.timezone or "UTC",
        "planned_week_number": record.planned_week_number,
        "planned_day_number": record.planned_day_number,
        "duration_seconds": record.duration_seconds,
        "average_heart_rate_bpm": record.average_heart_rate_bpm,
        "calories_burned": (
            float(record.calories_burned)
            if record.calories_burned is not None
            else None
        ),
        "notes": record.notes,
        "revision": record.revision,
        "updated_at": rfc3339(record.updated_at or record.created_at),
        "exercises": [
            {
                "exercise_order": exercise.exercise_order,
                "planned_exercise_order": exercise.planned_exercise_order,
                "name": exercise.name,
                "notes": exercise.notes,
                "sets": [
                    {
                        "set_number": item.set_number,
                        "planned_set_number": item.planned_set_number,
                        "weight_kg": float(item.weight_kg),
                        **(
                            {"load_details": item.load_details_json}
                            if item.load_details_json
                            else {}
                        ),
                        "reps": item.reps,
                        "rir": float(item.rir) if item.rir is not None else None,
                        "rpe": float(item.rpe) if item.rpe is not None else None,
                        "rest_seconds": item.rest_seconds,
                        "notes": item.notes,
                    }
                    for item in exercise.sets
                ],
            }
            for exercise in record.exercises
        ],
    }


def record_sync_change(
    *,
    user_id: int,
    entity_type: str,
    entity_public_id: str,
    operation: str,
    revision: int,
    payload: dict | None,
    device_id: int | None,
) -> SyncChange:
    change = SyncChange(
        user_id=user_id,
        entity_type=entity_type,
        entity_public_id=entity_public_id,
        operation=operation,
        revision=revision,
        changed_by_device_id=device_id,
        payload_hash=canonical_hash(payload or {"deleted": True}),
        payload_json=payload,
    )
    db.session.add(change)
    db.session.flush()
    return change


class PlannedWorkoutService:
    @staticmethod
    def schedule_from_plan_version(
        *,
        user_id: int,
        plan_public_id: str,
        version_public_id: str | None,
        scheduled_for_date: date,
        timezone_name: str,
        week_number: int,
        day_number: int,
        device_id: int | None = None,
        public_id: str | None = None,
    ) -> PlannedWorkout:
        validate_timezone(timezone_name)
        plan = _owned_plan(user_id, plan_public_id)
        version = _owned_version(user_id, plan, version_public_id)
        snapshot = _day_snapshot(version, week_number, day_number)
        try:
            public_id = str(uuid.UUID(public_id)) if public_id else str(uuid.uuid4())
        except ValueError as error:
            raise MobileSyncError("invalid_id", "El ID público no es válido.") from error
        existing = db.session.execute(
            db.select(PlannedWorkout).where(PlannedWorkout.public_id == public_id)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.user_id != user_id:
                raise MobileSyncError("not_found", "Entrenamiento no encontrado.", 404)
            raise MobileSyncError("conflict", "El ID ya existe.", 409)
        record = PlannedWorkout(
            public_id=public_id,
            user_id=user_id,
            training_plan_id=plan.id,
            training_plan_version_id=version.id,
            scheduled_for_date=scheduled_for_date,
            timezone=timezone_name,
            title_snapshot=snapshot["day"]["name"],
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

    @staticmethod
    def get_by_public_id(
        user_id: int, public_id: str, *, include_deleted: bool = False
    ) -> PlannedWorkout:
        statement = db.select(PlannedWorkout).where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.public_id == public_id,
        )
        if not include_deleted:
            statement = statement.where(PlannedWorkout.deleted_at.is_(None))
        record = db.session.execute(statement).scalar_one_or_none()
        if record is None:
            raise MobileSyncError("not_found", "Entrenamiento no encontrado.", 404)
        return record

    @staticmethod
    def list_range(user_id: int, start: date, end: date) -> list[PlannedWorkout]:
        return db.session.execute(
            db.select(PlannedWorkout)
            .where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.deleted_at.is_(None),
                PlannedWorkout.scheduled_for_date.between(start, end),
            )
            .order_by(PlannedWorkout.scheduled_for_date, PlannedWorkout.public_id)
        ).scalars().all()

    @staticmethod
    def reschedule(
        record: PlannedWorkout,
        *,
        scheduled_for_date: date,
        timezone_name: str,
        base_revision: int,
        device_id: int | None,
    ) -> PlannedWorkout:
        db.session.refresh(record, with_for_update=True)
        PlannedWorkoutService._check_revision(record, base_revision)
        if record.status in {"completed", "cancelled"}:
            raise MobileSyncError("invalid_transition", "El estado ya es final.", 409)
        validate_timezone(timezone_name)
        record.scheduled_for_date = scheduled_for_date
        record.timezone = timezone_name
        return PlannedWorkoutService._touch(record, device_id)

    @staticmethod
    def transition(
        record: PlannedWorkout,
        status: str,
        *,
        base_revision: int,
        device_id: int | None,
    ) -> PlannedWorkout:
        db.session.refresh(record, with_for_update=True)
        PlannedWorkoutService._check_revision(record, base_revision)
        allowed = {
            "planned": {"in_progress", "skipped", "cancelled"},
            "in_progress": {"completed", "skipped", "cancelled"},
            "skipped": {"planned"},
            "completed": set(),
            "cancelled": set(),
        }
        if status not in allowed.get(record.status, set()):
            raise MobileSyncError("invalid_transition", "Transición de estado no válida.", 409)
        record.status = status
        now = utcnow()
        if status == "completed":
            record.completed_at = now
        if status == "cancelled":
            record.cancelled_at = now
        return PlannedWorkoutService._touch(record, device_id)

    @staticmethod
    def tombstone(
        record: PlannedWorkout, *, base_revision: int, device_id: int | None
    ) -> PlannedWorkout:
        db.session.refresh(record, with_for_update=True)
        PlannedWorkoutService._check_revision(record, base_revision)
        if record.completed_session is not None:
            raise MobileSyncError("conflict", "Un entrenamiento completado no puede borrarse.", 409)
        record.deleted_at = utcnow()
        record.status = "cancelled"
        record.cancelled_at = record.cancelled_at or utcnow()
        record.revision += 1
        record.last_modified_by_device_id = device_id
        db.session.flush()
        record_sync_change(
            user_id=record.user_id,
            entity_type="planned_workout",
            entity_public_id=record.public_id,
            operation="delete",
            revision=record.revision,
            payload=None,
            device_id=device_id,
        )
        return record

    @staticmethod
    def _check_revision(record: PlannedWorkout, base_revision: int) -> None:
        if base_revision != record.revision:
            raise MobileSyncError(
                "revision_conflict",
                "La entidad cambió en el servidor.",
                409,
                {
                    "server_revision": record.revision,
                    "server_updated_at": rfc3339(record.updated_at),
                    "conflict_code": "stale_revision",
                    "resolution_options": ["refresh", "retry_with_current_revision"],
                },
            )

    @staticmethod
    def _touch(record: PlannedWorkout, device_id: int | None) -> PlannedWorkout:
        record.revision += 1
        record.updated_at = utcnow()
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
        return record


def _validate_completed_against_snapshot(payload: dict, snapshot: dict) -> None:
    planned = snapshot["day"]
    planned_exercises = {item["exercise_order"]: item for item in planned["exercises"]}
    exercise_orders = [item["exercise_order"] for item in payload["exercises"]]
    if len(set(exercise_orders)) != len(exercise_orders):
        raise MobileSyncError("invalid_workout", "El orden de ejercicios está duplicado.")
    for exercise in payload["exercises"]:
        planned_exercise = planned_exercises.get(exercise["planned_exercise_order"])
        if planned_exercise is None or planned_exercise["name"] != exercise["name"]:
            raise MobileSyncError("invalid_workout", "El ejercicio no coincide con el plan.")
        planned_sets = {item["set_number"] for item in planned_exercise["sets"]}
        if any(item["planned_set_number"] not in planned_sets for item in exercise["sets"]):
            raise MobileSyncError("invalid_workout", "Una serie no coincide con el plan.")


def create_completed_workout(
    *, user_id: int, device: ApiDevice, payload: dict, public_id: str | None = None
) -> tuple[TrainingSession, bool]:
    try:
        validate_json_document(payload, "completed_workout_api")
        from app.services.workout_loads import validate_completed_workout_loads

        validate_completed_workout_loads(payload)
    except (JsonSchemaValidationError, ValueError) as error:
        raise MobileSyncError("invalid_workout", str(error)) from error
    request_hash = canonical_hash(payload)
    existing = db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.user_id == user_id,
            TrainingSession.source_device_id == device.id,
            TrainingSession.client_event_id == payload["client_event_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.client_payload_sha256 == request_hash:
            return existing, True
        raise MobileSyncError(
            "event_conflict", "El client_event_id ya existe con otro contenido.", 409
        )

    planned = None
    if payload.get("planned_workout_id"):
        planned = PlannedWorkoutService.get_by_public_id(
            user_id, payload["planned_workout_id"]
        )
        db.session.refresh(planned, with_for_update=True)
        if planned.status not in {"planned", "in_progress"}:
            raise MobileSyncError("invalid_transition", "El entrenamiento planificado ya terminó.", 409)
        plan = planned.training_plan
        version = planned.training_plan_version
        snapshot = planned.payload_snapshot_json
        week_number = snapshot["week_number"]
        day_number = snapshot["day_number"]
    else:
        required = (
            "training_plan_id", "training_plan_version_id",
            "planned_week_number", "planned_day_number",
        )
        if any(payload.get(key) is None for key in required):
            raise MobileSyncError(
                "invalid_workout",
                "Sin planned_workout_id se requiere plan, versión, semana y día.",
            )
        plan = _owned_plan(user_id, payload["training_plan_id"])
        version = _owned_version(user_id, plan, payload["training_plan_version_id"])
        week_number = payload["planned_week_number"]
        day_number = payload["planned_day_number"]
        snapshot = _day_snapshot(version, week_number, day_number)

    _validate_completed_against_snapshot(payload, snapshot)
    started_at = parse_rfc3339(payload["started_at"], "started_at")
    completed_at = parse_rfc3339(payload["completed_at"], "completed_at")
    if completed_at < started_at:
        raise MobileSyncError("invalid_datetime", "completed_at debe ser posterior a started_at.")
    validate_timezone(payload["timezone"])

    try:
        public_id = str(uuid.UUID(public_id)) if public_id else str(uuid.uuid4())
    except ValueError as error:
        raise MobileSyncError("invalid_id", "El ID público no es válido.") from error
    occupied = db.session.execute(
        db.select(TrainingSession).where(TrainingSession.public_id == public_id)
    ).scalar_one_or_none()
    if occupied is not None:
        if occupied.user_id != user_id:
            raise MobileSyncError("not_found", "Sesión no encontrada.", 404)
        raise MobileSyncError("conflict", "El ID público ya existe.", 409)
    record = TrainingSession(
        public_id=public_id,
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        planned_workout_id=planned.id if planned else None,
        source_device_id=device.id,
        client_event_id=payload["client_event_id"],
        client_payload_sha256=request_hash,
        revision=1,
        performed_at=completed_at,
        started_at=started_at,
        completed_at=completed_at,
        timezone=payload["timezone"],
        planned_week_number=week_number,
        planned_day_number=day_number,
        duration_seconds=payload.get("duration_seconds") or int((completed_at - started_at).total_seconds()),
        average_heart_rate_bpm=payload.get("average_heart_rate_bpm"),
        calories_burned=(Decimal(str(payload["calories_burned"])) if payload.get("calories_burned") is not None else None),
        notes=payload.get("notes"),
    )
    db.session.add(record)
    db.session.flush()
    for exercise_data in payload["exercises"]:
        exercise = TrainingSessionExercise(
            user_id=user_id,
            training_session_id=record.id,
            exercise_order=exercise_data["exercise_order"],
            planned_exercise_order=exercise_data["planned_exercise_order"],
            name=exercise_data["name"],
            notes=exercise_data.get("notes"),
        )
        db.session.add(exercise)
        db.session.flush()
        for set_data in exercise_data["sets"]:
            from app.services.workout_loads import validate_load_details

            db.session.add(
                TrainingSet(
                    user_id=user_id,
                    training_session_exercise_id=exercise.id,
                    set_number=set_data["set_number"],
                    planned_set_number=set_data["planned_set_number"],
                    weight_kg=Decimal(str(set_data["weight_kg"])),
                    load_details_json=validate_load_details(
                        set_data["weight_kg"], set_data.get("load_details")
                    ),
                    reps=set_data["reps"],
                    rir=Decimal(str(set_data["rir"])) if set_data.get("rir") is not None else None,
                    rpe=Decimal(str(set_data["rpe"])) if set_data.get("rpe") is not None else None,
                    rest_seconds=set_data.get("rest_seconds"),
                    notes=set_data.get("notes"),
                )
            )
    db.session.flush()
    if planned:
        planned.status = "completed"
        planned.completed_at = completed_at
        PlannedWorkoutService._touch(planned, device.id)
    record_sync_change(
        user_id=user_id,
        entity_type="completed_workout",
        entity_public_id=record.public_id,
        operation="upsert",
        revision=record.revision,
        payload=serialize_completed_workout(record),
        device_id=device.id,
    )
    return record, False


def _cursor_signer():
    return URLSafeSerializer(
        current_app.config["API_TOKEN_SIGNING_KEY"],
        salt="health-tracker-mobile-sync-cursor-v1",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def encode_cursor(user_id: int, device_id: int, sequence: int) -> str:
    return _cursor_signer().dumps({"u": user_id, "d": device_id, "s": sequence, "v": 1})


def decode_cursor(value: str, user_id: int, device_id: int) -> int:
    try:
        data = _cursor_signer().loads(value)
    except BadData as error:
        raise MobileSyncError("invalid_cursor", "El cursor no es válido.", 400) from error
    if data.get("u") != user_id or data.get("d") != device_id or data.get("v") != 1:
        raise MobileSyncError("invalid_cursor", "El cursor no pertenece al dispositivo.", 400)
    sequence = data.get("s")
    if not isinstance(sequence, int) or sequence < 0:
        raise MobileSyncError("invalid_cursor", "El cursor no es válido.", 400)
    return sequence


def sync_state(user_id: int, device_id: int) -> DeviceSyncState:
    record = db.session.execute(
        db.select(DeviceSyncState).where(
            DeviceSyncState.user_id == user_id,
            DeviceSyncState.device_id == device_id,
        )
    ).scalar_one_or_none()
    if record is None:
        record = DeviceSyncState(user_id=user_id, device_id=device_id)
        db.session.add(record)
        db.session.flush()
    return record


def current_sequence(user_id: int) -> int:
    return db.session.execute(
        db.select(db.func.coalesce(db.func.max(SyncChange.sequence), 0)).where(
            SyncChange.user_id == user_id
        )
    ).scalar_one()


def claim_idempotency(
    *, user_id: int, device_id: int, raw_key: str, operation: str, payload: dict
) -> tuple[IdempotencyRecord, bool]:
    if not isinstance(raw_key, str) or not raw_key.strip() or len(raw_key) > 200:
        raise MobileSyncError("idempotency_required", "Se requiere Idempotency-Key.", 400)
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    request_hash = canonical_hash(payload)
    existing = db.session.execute(
        db.select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.device_id == device_id,
            IdempotencyRecord.key_hash == key_hash,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.operation != operation or existing.request_hash != request_hash:
            raise MobileSyncError(
                "idempotency_conflict", "La clave ya fue usada con otra solicitud.", 409
            )
        if existing.response_body_json is None:
            raise MobileSyncError("request_in_progress", "La solicitud sigue en curso.", 409)
        return existing, True
    record = IdempotencyRecord(
        user_id=user_id,
        device_id=device_id,
        key_hash=key_hash,
        operation=operation,
        request_hash=request_hash,
        expires_at=utcnow() + timedelta(days=current_app.config["SYNC_IDEMPOTENCY_DAYS"]),
    )
    try:
        with db.session.begin_nested():
            db.session.add(record)
            db.session.flush()
    except IntegrityError:
        existing = db.session.execute(
            db.select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.device_id == device_id,
                IdempotencyRecord.key_hash == key_hash,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise MobileSyncError("idempotency_conflict", "No fue posible reclamar la clave.", 409)
        if existing.operation != operation or existing.request_hash != request_hash:
            raise MobileSyncError(
                "idempotency_conflict", "La clave ya fue usada con otra solicitud.", 409
            )
        if existing.response_body_json is None:
            raise MobileSyncError("request_in_progress", "La solicitud sigue en curso.", 409)
        return existing, True
    return record, False


def finish_idempotency(record: IdempotencyRecord, data: dict, status: int) -> None:
    record.response_status = status
    record.response_body_json = data


def completed_workout_by_public_id(user_id: int, public_id: str) -> TrainingSession:
    record = db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.user_id == user_id,
            TrainingSession.public_id == public_id,
            TrainingSession.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if record is None:
        raise MobileSyncError("not_found", "Sesión no encontrada.", 404)
    return record
