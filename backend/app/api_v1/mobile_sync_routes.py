from datetime import date, datetime, timedelta, timezone

from flask import current_app, g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import failure, success
from app.api_v1.schemas import json_body
from app.api_v1.services import CAPABILITIES, active_routine
from app.extensions import db
from app.models import PlannedWorkout, SyncChange, TrainingSession
from app.services.mobile_sync import (
    MobileSyncError,
    PlannedWorkoutService,
    claim_idempotency,
    completed_workout_by_public_id,
    create_completed_workout,
    current_sequence,
    decode_cursor,
    encode_cursor,
    finish_idempotency,
    rfc3339,
    serialize_completed_workout,
    serialize_planned_workout,
    sync_state,
    utcnow,
)
from app.services.validation import JsonSchemaValidationError, validate_json_document


def _audit(event: str, *, entity_type: str | None = None) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s entity_type=%s",
        event,
        g.api_user.public_id[:8],
        g.api_session.device.public_device_id[:8],
        entity_type or "none",
    )


@api_v1_bp.errorhandler(MobileSyncError)
def handle_mobile_sync_error(error):
    return failure(error.code, str(error), error.status, error.details)


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _idempotent(operation: str, payload: dict, handler):
    record, replay = claim_idempotency(
        user_id=g.api_user.id,
        device_id=g.api_session.device_id,
        raw_key=request.headers.get("Idempotency-Key", ""),
        operation=operation,
        payload=payload,
    )
    if replay:
        _audit("idempotency_replay", entity_type=operation)
        return success(record.response_body_json, status=record.response_status)
    try:
        data, status = handler()
        finish_idempotency(record, data, status)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return success(data, status=status)


def _planned_payload(payload: dict, public_id: str | None = None):
    allowed = {
        "training_plan_id", "training_plan_version_id", "scheduled_for_date",
        "timezone", "week_number", "day_number", "base_revision",
    }
    if set(payload) - allowed:
        raise MobileSyncError("invalid_request", "La solicitud contiene campos desconocidos.")
    required = {"training_plan_id", "scheduled_for_date", "timezone", "week_number", "day_number"}
    if not required.issubset(payload):
        raise MobileSyncError("invalid_request", "Faltan campos del entrenamiento planificado.")
    for field in ("week_number", "day_number"):
        if not isinstance(payload[field], int) or payload[field] < 1:
            raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return PlannedWorkoutService.schedule_from_plan_version(
        user_id=g.api_user.id,
        plan_public_id=payload["training_plan_id"],
        version_public_id=payload.get("training_plan_version_id"),
        scheduled_for_date=_parse_date(payload["scheduled_for_date"], "scheduled_for_date"),
        timezone_name=payload["timezone"],
        week_number=payload["week_number"],
        day_number=payload["day_number"],
        device_id=g.api_session.device_id,
        public_id=public_id,
    )


def _planned_mutation_result(record: PlannedWorkout) -> dict:
    """Allowlisted replay body; snapshots stay out of idempotency storage."""
    return {
        "id": record.public_id,
        "status": record.status,
        "revision": record.revision,
        "scheduled_for_date": record.scheduled_for_date.isoformat(),
        "timezone": record.timezone,
        "updated_at": rfc3339(record.updated_at),
    }


@api_v1_bp.get("/planned-workouts")
@bearer_required
def planned_workouts_list():
    start = _parse_date(
        request.args.get("from", (date.today() - timedelta(days=14)).isoformat()),
        "from",
    )
    end = _parse_date(
        request.args.get("to", (date.today() + timedelta(days=30)).isoformat()),
        "to",
    )
    if end < start or (end - start).days > 366:
        raise MobileSyncError("invalid_range", "El rango solicitado no es válido.")
    records = PlannedWorkoutService.list_range(g.api_user.id, start, end)
    return success(
        [serialize_planned_workout(item) for item in records],
        extra_meta={"range": {"from": start.isoformat(), "to": end.isoformat()}},
    )


@api_v1_bp.post("/planned-workouts")
@bearer_required
def planned_workout_create():
    payload = json_body()

    def execute():
        record = _planned_payload(payload)
        _audit("planned_workout_created", entity_type="planned_workout")
        return _planned_mutation_result(record), 201

    return _idempotent("planned_workout_create", payload, execute)


@api_v1_bp.get("/planned-workouts/<public_id>")
@bearer_required
def planned_workout_detail(public_id):
    return success(
        serialize_planned_workout(
            PlannedWorkoutService.get_by_public_id(g.api_user.id, public_id)
        )
    )


@api_v1_bp.patch("/planned-workouts/<public_id>")
@bearer_required
def planned_workout_patch(public_id):
    payload = json_body()

    def execute():
        allowed = {"scheduled_for_date", "timezone", "base_revision"}
        if set(payload) - allowed or not allowed.issubset(payload):
            raise MobileSyncError("invalid_request", "La reprogramación no es válida.")
        record = PlannedWorkoutService.get_by_public_id(g.api_user.id, public_id)
        PlannedWorkoutService.reschedule(
            record,
            scheduled_for_date=_parse_date(payload["scheduled_for_date"], "scheduled_for_date"),
            timezone_name=payload["timezone"],
            base_revision=payload["base_revision"],
            device_id=g.api_session.device_id,
        )
        _audit("planned_workout_transition", entity_type="planned_workout")
        return _planned_mutation_result(record), 200

    return _idempotent(f"planned_workout_patch:{public_id}", payload, execute)


def _transition(public_id: str, status: str):
    payload = json_body()

    def execute():
        if set(payload) != {"base_revision"} or not isinstance(payload["base_revision"], int):
            raise MobileSyncError("invalid_request", "Se requiere base_revision.")
        record = PlannedWorkoutService.get_by_public_id(g.api_user.id, public_id)
        PlannedWorkoutService.transition(
            record,
            status,
            base_revision=payload["base_revision"],
            device_id=g.api_session.device_id,
        )
        _audit("planned_workout_transition", entity_type="planned_workout")
        return _planned_mutation_result(record), 200

    return _idempotent(f"planned_workout_{status}:{public_id}", payload, execute)


@api_v1_bp.post("/planned-workouts/<public_id>/start")
@bearer_required
def planned_workout_start(public_id):
    return _transition(public_id, "in_progress")


@api_v1_bp.post("/planned-workouts/<public_id>/skip")
@bearer_required
def planned_workout_skip(public_id):
    return _transition(public_id, "skipped")


@api_v1_bp.post("/planned-workouts/<public_id>/cancel")
@bearer_required
def planned_workout_cancel(public_id):
    return _transition(public_id, "cancelled")


@api_v1_bp.post("/completed-workouts")
@bearer_required
def completed_workout_create():
    payload = json_body()

    def execute():
        record, duplicate = create_completed_workout(
            user_id=g.api_user.id, device=g.api_session.device, payload=payload
        )
        _audit("completed_workout_uploaded", entity_type="completed_workout")
        data = serialize_completed_workout(record)
        summary = {
            "id": data["id"],
            "client_event_id": data["client_event_id"],
            "planned_workout_id": data["planned_workout_id"],
            "revision": data["revision"],
            "duplicate": duplicate,
        }
        return summary, 200 if duplicate else 201

    return _idempotent("completed_workout_create", payload, execute)


@api_v1_bp.get("/completed-workouts")
@bearer_required
def completed_workouts_list():
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    records = db.session.execute(
        db.select(TrainingSession)
        .where(
            TrainingSession.user_id == g.api_user.id,
            TrainingSession.deleted_at.is_(None),
        )
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.public_id)
        .limit(limit)
    ).scalars().all()
    return success([serialize_completed_workout(item) for item in records])


@api_v1_bp.get("/completed-workouts/<public_id>")
@bearer_required
def completed_workout_detail(public_id):
    return success(
        serialize_completed_workout(
            completed_workout_by_public_id(g.api_user.id, public_id)
        )
    )


@api_v1_bp.get("/sync/bootstrap")
@bearer_required
def sync_bootstrap():
    now = date.today()
    start = now - timedelta(days=current_app.config["SYNC_BOOTSTRAP_PAST_DAYS"])
    end = now + timedelta(days=current_app.config["SYNC_BOOTSTRAP_FUTURE_DAYS"])
    planned = PlannedWorkoutService.list_range(g.api_user.id, start, end)
    completed = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == g.api_user.id, TrainingSession.deleted_at.is_(None))
        .order_by(TrainingSession.performed_at.desc())
        .limit(25)
    ).scalars().all()
    sequence = current_sequence(g.api_user.id)
    state = sync_state(g.api_user.id, g.api_session.device_id)
    state.last_pull_sequence = sequence
    db.session.commit()
    data = {
        "schema_version": "1.0",
        "server_time": rfc3339(datetime.now(timezone.utc)),
        "cursor": encode_cursor(g.api_user.id, g.api_session.device_id, sequence),
        "active_routine": active_routine(g.api_user.id),
        "planned_workouts": [serialize_planned_workout(item) for item in planned],
        "completed_workouts": [serialize_completed_workout(item) for item in completed],
        "capabilities": CAPABILITIES,
        "limits": {
            "push_operations": current_app.config["SYNC_PUSH_MAX_OPERATIONS"],
            "pull_limit": current_app.config["SYNC_PULL_MAX_LIMIT"],
            "json_bytes": current_app.config["API_JSON_MAX_BYTES"],
        },
        "schemas": {
            "planned_workout": "1.0",
            "completed_workout": "1.0",
            "sync": "1.0",
        },
        "device": {
            "device_id": g.api_session.device.public_device_id,
            "session_id": g.api_session.public_session_id,
        },
    }
    return success(data)


@api_v1_bp.get("/sync/pull")
@bearer_required
def sync_pull():
    cursor = request.args.get("cursor", "")
    after = decode_cursor(cursor, g.api_user.id, g.api_session.device_id)
    limit = request.args.get("limit", 100, type=int)
    if limit < 1 or limit > current_app.config["SYNC_PULL_MAX_LIMIT"]:
        raise MobileSyncError("invalid_limit", "El límite de pull no es válido.")
    requested_types = {
        item.strip() for item in request.args.get("entity_types", "").split(",") if item.strip()
    }
    if requested_types - {"planned_workout", "completed_workout"}:
        raise MobileSyncError("unsupported_entity", "El filtro contiene una entidad no soportada.")
    statement = db.select(SyncChange).where(
        SyncChange.user_id == g.api_user.id, SyncChange.sequence > after
    )
    scanned = db.session.execute(
        statement.order_by(SyncChange.sequence).limit(limit + 1)
    ).scalars().all()
    has_more = len(scanned) > limit
    scanned = scanned[:limit]
    next_sequence = scanned[-1].sequence if scanned else after
    records = [
        item for item in scanned
        if not requested_types or item.entity_type in requested_types
    ]
    state = sync_state(g.api_user.id, g.api_session.device_id)
    state.last_pull_sequence = max(state.last_pull_sequence, next_sequence)
    db.session.commit()
    changes = [
        {
            "entity_type": item.entity_type,
            "entity_id": item.entity_public_id,
            "operation": item.operation,
            "revision": item.revision,
            "changed_at": rfc3339(item.changed_at),
            "payload_hash": item.payload_hash,
            "payload": item.payload_json,
        }
        for item in records
    ]
    _audit("sync_pull")
    return success({
        "schema_version": "1.0",
        "changes": changes,
        "next_cursor": encode_cursor(g.api_user.id, g.api_session.device_id, next_sequence),
        "has_more": has_more,
        "server_time": rfc3339(utcnow()),
    })


def _push_operation(item: dict) -> dict:
    entity_type = item["entity_type"]
    operation = item["operation"]
    entity_id = item["entity_id"]
    payload = item["payload"]
    if entity_type == "planned_workout":
        if operation == "upsert":
            try:
                record = PlannedWorkoutService.get_by_public_id(g.api_user.id, entity_id)
            except MobileSyncError as error:
                if error.code != "not_found":
                    raise
                record = _planned_payload(payload, public_id=entity_id)
            else:
                if item.get("base_revision") is None:
                    raise MobileSyncError("invalid_request", "Se requiere base_revision.")
                PlannedWorkoutService.reschedule(
                    record,
                    scheduled_for_date=_parse_date(payload["scheduled_for_date"], "scheduled_for_date"),
                    timezone_name=payload["timezone"],
                    base_revision=item["base_revision"],
                    device_id=g.api_session.device_id,
                )
            return {"status": "accepted", "entity_id": record.public_id, "revision": record.revision}
        record = PlannedWorkoutService.get_by_public_id(g.api_user.id, entity_id)
        if item.get("base_revision") is None:
            raise MobileSyncError("invalid_request", "Se requiere base_revision.")
        if operation == "delete":
            PlannedWorkoutService.tombstone(record, base_revision=item["base_revision"], device_id=g.api_session.device_id)
            _audit("tombstone_created", entity_type=entity_type)
        elif operation == "transition":
            status = payload.get("status")
            if status not in {"planned", "in_progress", "skipped", "cancelled"}:
                raise MobileSyncError("invalid_transition", "El estado solicitado no es válido.")
            PlannedWorkoutService.transition(record, status, base_revision=item["base_revision"], device_id=g.api_session.device_id)
        else:
            raise MobileSyncError("unsupported_operation", "Operación no soportada.", 400)
        return {"status": "accepted", "entity_id": record.public_id, "revision": record.revision}
    if entity_type == "completed_workout" and operation == "upsert":
        record, duplicate = create_completed_workout(
            user_id=g.api_user.id,
            device=g.api_session.device,
            payload=payload,
            public_id=entity_id,
        )
        return {
            "status": "duplicate" if duplicate else "accepted",
            "entity_id": record.public_id,
            "revision": record.revision,
        }
    raise MobileSyncError("unsupported_entity", "Entidad u operación no soportada.", 400)


@api_v1_bp.post("/sync/push")
@bearer_required
def sync_push():
    payload = json_body()
    try:
        validate_json_document(payload, "sync_push")
    except JsonSchemaValidationError as error:
        raise MobileSyncError("invalid_batch", str(error)) from error
    if len(payload["operations"]) > current_app.config["SYNC_PUSH_MAX_OPERATIONS"]:
        raise MobileSyncError("batch_too_large", "El lote excede el límite.", 413)

    def execute():
        results = []
        seen = set()
        for item in payload["operations"]:
            operation_id = item["client_operation_id"]
            if operation_id in seen:
                results.append({"client_operation_id": operation_id, "status": "invalid", "error_code": "duplicate_operation_in_batch"})
                continue
            seen.add(operation_id)
            try:
                with db.session.begin_nested():
                    operation_record, replay = claim_idempotency(
                        user_id=g.api_user.id,
                        device_id=g.api_session.device_id,
                        raw_key=f"sync-operation:{operation_id}",
                        operation="sync_operation",
                        payload=item,
                    )
                    if replay:
                        result = dict(operation_record.response_body_json)
                        result["status"] = "duplicate"
                    else:
                        result = _push_operation(item)
                        finish_idempotency(operation_record, result, 200)
            except MobileSyncError as error:
                mapping = {
                    403: "forbidden", 404: "forbidden", 409: "conflict"
                }
                status = (
                    "unsupported"
                    if error.code in {"unsupported_entity", "unsupported_operation"}
                    else mapping.get(error.status, "invalid")
                )
                result = {
                    "status": status,
                    "error_code": error.code,
                }
                if error.details:
                    result["conflict"] = error.details
                _audit("sync_conflict", entity_type=item["entity_type"])
            result["client_operation_id"] = operation_id
            results.append(result)
        state = sync_state(g.api_user.id, g.api_session.device_id)
        state.last_push_at = utcnow()
        summary = {
            status: sum(item["status"] == status for item in results)
            for status in ("accepted", "duplicate", "conflict", "invalid", "forbidden", "unsupported")
        }
        _audit("sync_push")
        return {
            "schema_version": "1.0",
            "batch_id": payload["batch_id"],
            "results": results,
            "summary": summary,
            "server_time": rfc3339(utcnow()),
        }, 200

    return _idempotent("sync_push", payload, execute)


@api_v1_bp.get("/sync/status")
@bearer_required
def sync_status():
    state = sync_state(g.api_user.id, g.api_session.device_id)
    server_sequence = current_sequence(g.api_user.id)
    db.session.commit()
    return success({
        "schema_version": "1.0",
        "device_id": g.api_session.device.public_device_id,
        "cursor": encode_cursor(g.api_user.id, g.api_session.device_id, state.last_pull_sequence),
        "last_pull_at_sequence": state.last_pull_sequence,
        "last_push_at": rfc3339(state.last_push_at),
        "server_sequence": server_sequence,
        "server_time": rfc3339(utcnow()),
    })
