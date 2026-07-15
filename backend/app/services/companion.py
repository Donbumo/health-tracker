import json
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ApiDevice,
    CompanionDeviceProfile,
    CompanionProgressEvent,
    CompanionWorkoutDelivery,
    PlannedWorkout,
)
from app.services.mobile_sync import (
    MobileSyncError,
    PlannedWorkoutService,
    canonical_hash,
    create_completed_workout,
    parse_rfc3339,
    record_sync_change,
    rfc3339,
    serialize_completed_workout,
    utcnow,
)
from app.services.validation import JsonSchemaValidationError, validate_json_document


PROTOCOL_VERSIONS = ("1.0",)
WORKOUT_SCHEMA_VERSIONS = ("1.0",)
RESULT_SCHEMA_VERSIONS = ("1.0",)
FEATURES = {
    "offline", "rest_timer", "haptics", "rpe", "rir", "weight",
    "heart_rate_summary", "calories_summary",
}
METRICS = {
    "reps", "weight_kg", "duration_seconds", "distance_m", "rest_seconds",
    "rpe", "rir", "average_heart_rate_bpm", "calories_burned",
}
PROGRESS_TYPES = {
    "heartbeat", "exercise_started", "set_completed", "exercise_completed",
    "paused", "resumed", "checkpoint",
}
PROGRESS_FIELDS = {
    "exercise_order", "set_number", "completed_reps", "weight_kg", "rir",
    "rpe", "elapsed_seconds", "rest_seconds", "message_code",
}
FAILURE_CODES = {
    "client_error", "storage_error", "workout_unavailable", "user_cancelled",
    "device_shutdown", "unknown",
}
TERMINAL_STATUSES = {"completed", "aborted", "failed", "expired", "cancelled"}
SERVER_LIMITS = {"max_payload_bytes": 262144, "max_progress_events_per_workout": 500}

SERVER_CAPABILITIES = {
    "companion_delivery": True,
    "capability_negotiation": True,
    "progress_checkpoints": True,
    "workout_package": True,
    "watch_bridge": False,
    "bluetooth_bridge": False,
    "continuous_telemetry": False,
    "fit_output": False,
    "vendor_huawei": False,
    "vendor_garmin": False,
    "vendor_magene": False,
}


def _uuid(value, field):
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_request", f"{field} debe ser UUID.") from error


def _list_of_strings(payload, field, *, maximum=64):
    value = payload.get(field)
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise MobileSyncError("invalid_request", f"{field} debe ser una lista no vacía.")
    if any(not isinstance(item, str) or not item or len(item) > 64 for item in value):
        raise MobileSyncError("invalid_request", f"{field} contiene valores inválidos.")
    return list(dict.fromkeys(value))


def _select_version(requested, supported, error_code):
    selected = next((item for item in supported if item in requested), None)
    if selected is None:
        raise MobileSyncError(error_code, "No existe una versión compatible.", 409, {"supported": list(supported)})
    return selected


def serialize_profile(profile):
    payload = {
        "schema_version": "1.0",
        "id": profile.public_id,
        "device_id": profile.api_device.public_device_id,
        "protocol_version": profile.protocol_version,
        "workout_schema_version": profile.workout_schema_version,
        "result_schema_version": profile.result_schema_version,
        "supported_features": list(profile.supported_features_json or []),
        "supported_metrics": list(profile.supported_metrics_json or []),
        "limits": {
            "max_payload_bytes": profile.max_payload_bytes,
            "max_progress_events_per_workout": profile.max_progress_events_per_workout,
        },
        "supports_offline": profile.supports_offline,
        "supports_rest_timer": profile.supports_rest_timer,
        "supports_haptics": profile.supports_haptics,
        "supports_rpe": profile.supports_rpe,
        "supports_rir": profile.supports_rir,
        "supports_weight": profile.supports_weight,
        "supports_heart_rate_summary": profile.supports_heart_rate_summary,
        "supports_calories_summary": profile.supports_calories_summary,
        "revision": profile.revision,
        "last_negotiated_at": rfc3339(profile.last_negotiated_at),
        "revoked": profile.revoked_at is not None,
    }
    validate_json_document(payload, "companion_device_profile")
    return payload


def get_profile(user_id, device_id, *, required=True):
    profile = db.session.execute(
        db.select(CompanionDeviceProfile).where(
            CompanionDeviceProfile.user_id == user_id,
            CompanionDeviceProfile.api_device_id == device_id,
        )
    ).scalar_one_or_none()
    if required and (profile is None or profile.revoked_at is not None):
        raise MobileSyncError("capability_profile_required", "El dispositivo debe negociar capacidades.", 409)
    return profile


def negotiate_profile(*, user_id, device, payload):
    try:
        validate_json_document(payload, "companion_negotiation")
    except JsonSchemaValidationError as error:
        raise MobileSyncError("invalid_request", str(error)) from error
    allowed = {
        "schema_version", "protocol_versions", "workout_schema_versions",
        "result_schema_versions", "features", "metrics", "limits", "base_revision",
    }
    if set(payload) - allowed or payload.get("schema_version") != "1.0":
        raise MobileSyncError("invalid_request", "La negociación no es válida.")
    if device.user_id != user_id or device.revoked_at is not None:
        raise MobileSyncError("not_found", "Dispositivo no encontrado.", 404)
    protocols = _list_of_strings(payload, "protocol_versions")
    workout_versions = _list_of_strings(payload, "workout_schema_versions")
    result_versions = _list_of_strings(payload, "result_schema_versions")
    requested_features = _list_of_strings(payload, "features")
    requested_metrics = _list_of_strings(payload, "metrics")
    limits = payload.get("limits", {})
    if not isinstance(limits, dict) or set(limits) - set(SERVER_LIMITS):
        raise MobileSyncError("invalid_request", "Los límites solicitados no son válidos.")
    server_limits = {
        "max_payload_bytes": current_app.config["COMPANION_PACKAGE_MAX_BYTES"],
        "max_progress_events_per_workout": current_app.config["COMPANION_PROGRESS_MAX_EVENTS"],
    }
    for key, default in server_limits.items():
        value = limits.get(key, default)
        if not isinstance(value, int) or value < 1:
            raise MobileSyncError("invalid_request", "Los límites solicitados no son válidos.")

    protocol = _select_version(protocols, PROTOCOL_VERSIONS, "companion_protocol_unsupported")
    workout_version = _select_version(workout_versions, WORKOUT_SCHEMA_VERSIONS, "workout_schema_unsupported")
    result_version = _select_version(result_versions, RESULT_SCHEMA_VERSIONS, "result_schema_unsupported")
    accepted_features = sorted(set(requested_features) & FEATURES)
    rejected_features = sorted(set(requested_features) - FEATURES)
    accepted_metrics = sorted(set(requested_metrics) & METRICS)
    rejected_metrics = sorted(set(requested_metrics) - METRICS)
    effective_limits = {
        key: min(limits.get(key, maximum), maximum)
        for key, maximum in server_limits.items()
    }

    profile = get_profile(user_id, device.id, required=False)
    now = utcnow()
    if profile is None:
        profile = CompanionDeviceProfile(
            user_id=user_id,
            api_device_id=device.id,
            supported_features_json=accepted_features,
            supported_metrics_json=accepted_metrics,
        )
        db.session.add(profile)
    else:
        db.session.refresh(profile, with_for_update=True)
        base_revision = payload.get("base_revision")
        if base_revision is None or base_revision != profile.revision:
            raise MobileSyncError(
                "revision_conflict", "El perfil cambió en el servidor.", 409,
                {"server_revision": profile.revision},
            )
        profile.revision += 1
        profile.supported_features_json = accepted_features
        profile.supported_metrics_json = accepted_metrics
    profile.protocol_version = protocol
    profile.workout_schema_version = workout_version
    profile.result_schema_version = result_version
    profile.max_payload_bytes = max(1024, effective_limits["max_payload_bytes"])
    profile.max_progress_events_per_workout = max(1, effective_limits["max_progress_events_per_workout"])
    profile.supports_offline = "offline" in accepted_features
    for feature in FEATURES - {"offline"}:
        setattr(profile, f"supports_{feature}", feature in accepted_features)
    profile.last_negotiated_at = now
    profile.updated_at = now
    db.session.flush()
    summary = serialize_profile(profile)
    record_sync_change(
        user_id=user_id, entity_type="companion_profile",
        entity_public_id=profile.public_id, operation="upsert", revision=profile.revision,
        payload=summary, device_id=device.id,
    )
    return profile, {
        "selected_protocol_version": protocol,
        "selected_workout_schema_version": workout_version,
        "selected_result_schema_version": result_version,
        "accepted_features": accepted_features,
        "rejected_features": rejected_features,
        "accepted_metrics": accepted_metrics,
        "rejected_metrics": rejected_metrics,
        "effective_limits": effective_limits,
        "server_capabilities": SERVER_CAPABILITIES,
        "profile": summary,
    }


def _package_exercises(planned, profile):
    exercises = []
    dropped = []
    for exercise in planned.payload_snapshot_json["day"]["exercises"]:
        output = {
            "exercise_order": exercise["exercise_order"],
            "name": exercise["name"],
            "sets": [],
        }
        if exercise.get("notes"):
            output["notes"] = exercise["notes"][:2000]
        for item in exercise["sets"]:
            allowed = {
                key: item[key]
                for key in ("set_number", "reps", "reps_min", "reps_max", "duration_seconds", "distance_m", "target")
                if key in item
            }
            if "rest_seconds" in item:
                if profile.supports_rest_timer:
                    allowed["rest_seconds"] = item["rest_seconds"]
                else:
                    dropped.append(f"exercises[{len(exercises)}].sets[{len(output['sets'])}].rest_seconds")
            output["sets"].append(allowed)
        exercises.append(output)
    return exercises, dropped


def serialize_delivery(delivery, *, include_package=False):
    data = {
        "schema_version": "1.0",
        "id": delivery.public_id,
        "device_id": delivery.api_device.public_device_id,
        "profile_id": delivery.profile.public_id,
        "planned_workout_id": delivery.planned_workout.public_id,
        "package_schema_version": delivery.package_schema_version,
        "package_hash": delivery.package_hash,
        "status": delivery.status,
        "revision": delivery.revision,
        "last_client_sequence": delivery.last_client_sequence,
        "created_at": rfc3339(delivery.created_at),
        "updated_at": rfc3339(delivery.updated_at),
        "delivered_at": rfc3339(delivery.delivered_at),
        "acknowledged_at": rfc3339(delivery.acknowledged_at),
        "started_at": rfc3339(delivery.started_at),
        "completed_at": rfc3339(delivery.completed_at),
        "aborted_at": rfc3339(delivery.aborted_at),
        "failed_at": rfc3339(delivery.failed_at),
        "expires_at": rfc3339(delivery.expires_at),
        "failure_code": delivery.failure_code,
        "training_session_id": delivery.training_session.public_id if delivery.training_session else None,
    }
    if include_package:
        data["package"] = delivery.payload_snapshot_json
    validate_json_document(data, "companion_delivery")
    return data


def _record_delivery_change(delivery):
    record_sync_change(
        user_id=delivery.user_id, entity_type="companion_delivery",
        entity_public_id=delivery.public_id, operation="upsert", revision=delivery.revision,
        payload=serialize_delivery(delivery), device_id=delivery.api_device_id,
    )


def prepare_delivery(*, user_id, device, planned_public_id, mark_delivered=True, expires_at=None):
    if device.user_id != user_id or device.revoked_at is not None:
        raise MobileSyncError("not_found", "Dispositivo no encontrado.", 404)
    profile = get_profile(user_id, device.id)
    planned = PlannedWorkoutService.get_by_public_id(user_id, planned_public_id)
    if planned.status not in {"planned", "in_progress"}:
        raise MobileSyncError("delivery_state_conflict", "El entrenamiento no admite una entrega.", 409)
    existing = db.session.execute(
        db.select(CompanionWorkoutDelivery).where(
            CompanionWorkoutDelivery.user_id == user_id,
            CompanionWorkoutDelivery.api_device_id == device.id,
            CompanionWorkoutDelivery.profile_id == profile.id,
            CompanionWorkoutDelivery.planned_workout_id == planned.id,
            CompanionWorkoutDelivery.planned_workout_revision == planned.revision,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True
    public_id = str(uuid.uuid4())
    generated_at = utcnow()
    exercises, dropped = _package_exercises(planned, profile)
    package = {
        "schema_version": profile.workout_schema_version,
        "package_id": public_id,
        "planned_workout_id": planned.public_id,
        "plan_id": planned.training_plan.public_id,
        "plan_version_id": planned.training_plan_version.public_id,
        "title": planned.title_snapshot,
        "scheduled_for_date": planned.scheduled_for_date.isoformat(),
        "timezone": planned.timezone,
        "revision": planned.revision,
        "generated_at": rfc3339(generated_at),
        "expires_at": rfc3339(expires_at),
        "exercises": exercises,
        "supported_metrics": list(profile.supported_metrics_json or []),
        "unsupported_fields": dropped,
        "server_capabilities": SERVER_CAPABILITIES,
        "device_capabilities": {
            "features": list(profile.supported_features_json or []),
            "metrics": list(profile.supported_metrics_json or []),
        },
        "compatibility_warnings": (["unsupported_fields_dropped"] if dropped else []),
    }
    package_hash = canonical_hash(package)
    package["package_hash"] = package_hash
    validate_json_document(package, "companion_workout_package")
    encoded_size = len(json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if encoded_size > profile.max_payload_bytes:
        raise MobileSyncError("package_too_large", "El paquete supera el límite negociado.", 413, {"size_bytes": encoded_size, "limit_bytes": profile.max_payload_bytes})
    delivery = CompanionWorkoutDelivery(
        public_id=public_id, user_id=user_id, api_device_id=device.id,
        profile_id=profile.id, planned_workout_id=planned.id,
        planned_workout_revision=planned.revision,
        package_schema_version=profile.workout_schema_version,
        package_hash=package_hash, payload_snapshot_json=package,
        status="delivered" if mark_delivered else "prepared",
        delivered_at=generated_at if mark_delivered else None,
        expires_at=expires_at,
        created_at=generated_at, updated_at=generated_at,
    )
    try:
        with db.session.begin_nested():
            db.session.add(delivery)
            db.session.flush()
    except IntegrityError:
        existing = db.session.execute(
            db.select(CompanionWorkoutDelivery).where(
                CompanionWorkoutDelivery.api_device_id == device.id,
                CompanionWorkoutDelivery.profile_id == profile.id,
                CompanionWorkoutDelivery.planned_workout_id == planned.id,
                CompanionWorkoutDelivery.planned_workout_revision == planned.revision,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise MobileSyncError("delivery_state_conflict", "No fue posible preparar la entrega.", 409)
        return existing, True
    _record_delivery_change(delivery)
    return delivery, False


def owned_delivery(user_id, device_id, public_id, *, lock=False):
    statement = db.select(CompanionWorkoutDelivery).where(
        CompanionWorkoutDelivery.user_id == user_id,
        CompanionWorkoutDelivery.api_device_id == device_id,
        CompanionWorkoutDelivery.public_id == public_id,
    )
    if lock:
        statement = statement.with_for_update()
    delivery = db.session.execute(statement).scalar_one_or_none()
    if delivery is None:
        raise MobileSyncError("not_found", "Entrega no encontrada.", 404)
    return delivery


def transition_delivery(delivery, *, action, base_revision, package_hash=None, failure_code=None):
    db.session.refresh(delivery, with_for_update=True)
    if delivery.revision != base_revision:
        raise MobileSyncError("revision_conflict", "La entrega cambió en el servidor.", 409, {"server_revision": delivery.revision})
    if delivery.status in TERMINAL_STATUSES:
        raise MobileSyncError("delivery_state_conflict", "La entrega ya está en estado terminal.", 409)
    if delivery.expires_at is not None:
        expires_at = delivery.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utcnow():
            raise MobileSyncError("delivery_state_conflict", "La entrega está expirada.", 409)
    now = utcnow()
    if action == "ack":
        if package_hash != delivery.package_hash:
            raise MobileSyncError("package_hash_mismatch", "El hash del paquete no coincide.", 409)
        delivery.status = "acknowledged"
        delivery.acknowledged_at = now
    elif action == "start":
        if delivery.status not in {"delivered", "acknowledged"}:
            raise MobileSyncError("delivery_state_conflict", "La entrega no puede iniciarse.", 409)
        delivery.status = "started"
        delivery.started_at = now
    elif action == "abort":
        if failure_code not in FAILURE_CODES:
            raise MobileSyncError("invalid_request", "reason_code no está permitido.")
        delivery.status = "aborted"
        delivery.aborted_at = now
        delivery.failure_code = failure_code
    elif action == "fail":
        if failure_code not in FAILURE_CODES:
            raise MobileSyncError("invalid_request", "failure_code no está permitido.")
        delivery.status = "failed"
        delivery.failed_at = now
        delivery.failure_code = failure_code
    else:
        raise MobileSyncError("invalid_request", "Acción no soportada.")
    delivery.revision += 1
    delivery.updated_at = now
    db.session.flush()
    _record_delivery_change(delivery)
    return delivery


def add_progress(*, delivery, device, payload):
    try:
        validate_json_document(payload, "companion_progress_event")
    except JsonSchemaValidationError as error:
        raise MobileSyncError("invalid_request", str(error)) from error
    allowed = {"schema_version", "client_event_id", "client_sequence", "event_type", "occurred_at", "payload"}
    if set(payload) != allowed or payload.get("schema_version") != "1.0":
        raise MobileSyncError("invalid_request", "El checkpoint no es válido.")
    client_event_id = _uuid(payload["client_event_id"], "client_event_id")
    sequence = payload["client_sequence"]
    event_type = payload["event_type"]
    event_payload = payload["payload"]
    if not isinstance(sequence, int) or sequence < 1 or event_type not in PROGRESS_TYPES:
        raise MobileSyncError("invalid_request", "El checkpoint no es válido.")
    if not isinstance(event_payload, dict) or set(event_payload) - PROGRESS_FIELDS:
        raise MobileSyncError("invalid_request", "El payload del checkpoint contiene campos no permitidos.")
    if any(isinstance(value, (list, dict)) for value in event_payload.values()):
        raise MobileSyncError("invalid_request", "No se permite telemetría anidada.")
    if len(json.dumps(event_payload, ensure_ascii=False).encode("utf-8")) > 2048:
        raise MobileSyncError("payload_too_large", "El checkpoint supera el límite.", 413)
    occurred_at = parse_rfc3339(payload["occurred_at"], "occurred_at")
    event_hash = canonical_hash(payload)
    db.session.refresh(delivery, with_for_update=True)
    existing = db.session.execute(
        db.select(CompanionProgressEvent).where(
            CompanionProgressEvent.delivery_id == delivery.id,
            CompanionProgressEvent.client_event_id == client_event_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash == event_hash:
            return existing, True
        raise MobileSyncError("progress_event_conflict", "El evento ya existe con otro contenido.", 409)
    if delivery.status in TERMINAL_STATUSES:
        raise MobileSyncError("delivery_state_conflict", "No se aceptan eventos tras finalizar.", 409)
    if delivery.status != "started":
        raise MobileSyncError("delivery_state_conflict", "La entrega no está iniciada.", 409)
    expected = delivery.last_client_sequence + 1
    if sequence != expected:
        raise MobileSyncError("progress_sequence_conflict", "La secuencia no es la esperada.", 409, {"expected_sequence": expected})
    count = db.session.execute(
        db.select(db.func.count(CompanionProgressEvent.id)).where(CompanionProgressEvent.delivery_id == delivery.id)
    ).scalar_one()
    if count >= delivery.profile.max_progress_events_per_workout:
        raise MobileSyncError("progress_limit_reached", "Se alcanzó el límite de checkpoints.", 413)
    event = CompanionProgressEvent(
        user_id=delivery.user_id, delivery_id=delivery.id, api_device_id=device.id,
        client_event_id=client_event_id, client_sequence=sequence,
        event_type=event_type, occurred_at=occurred_at,
        payload_json=event_payload, payload_hash=event_hash,
    )
    db.session.add(event)
    delivery.last_client_sequence = sequence
    delivery.updated_at = utcnow()
    db.session.flush()
    return event, False


def serialize_progress(event):
    return {
        "schema_version": "1.0", "id": event.public_id,
        "delivery_id": event.delivery.public_id,
        "client_event_id": event.client_event_id,
        "client_sequence": event.client_sequence,
        "event_type": event.event_type,
        "occurred_at": rfc3339(event.occurred_at),
        "payload": event.payload_json,
        "created_at": rfc3339(event.created_at),
    }


def complete_delivery(*, delivery, device, payload):
    try:
        validate_json_document(payload, "companion_completion")
    except JsonSchemaValidationError as error:
        raise MobileSyncError("invalid_request", str(error)) from error
    allowed = {"schema_version", "client_event_id", "package_hash", "base_revision", "result"}
    if set(payload) != allowed or payload.get("schema_version") != "1.0" or not isinstance(payload.get("result"), dict):
        raise MobileSyncError("invalid_request", "El resultado companion no es válido.")
    event_id = _uuid(payload["client_event_id"], "client_event_id")
    request_hash = canonical_hash(payload)
    db.session.refresh(delivery, with_for_update=True)
    if delivery.status == "completed":
        if delivery.completion_event_id == event_id and delivery.completion_payload_hash == request_hash:
            return delivery.training_session, True
        raise MobileSyncError("progress_event_conflict", "La finalización ya existe con otro contenido.", 409)
    if delivery.status in TERMINAL_STATUSES or delivery.status not in {"acknowledged", "started"}:
        raise MobileSyncError("delivery_state_conflict", "La entrega no se puede completar.", 409)
    if payload["base_revision"] != delivery.revision:
        raise MobileSyncError("revision_conflict", "La entrega cambió en el servidor.", 409, {"server_revision": delivery.revision})
    if payload["package_hash"] != delivery.package_hash:
        raise MobileSyncError("package_hash_mismatch", "El hash del paquete no coincide.", 409)
    result = payload["result"]
    if result.get("client_event_id") != event_id or result.get("planned_workout_id") != delivery.planned_workout.public_id:
        raise MobileSyncError("capability_mismatch", "El resultado no corresponde a la entrega.", 409)
    session, duplicate = create_completed_workout(user_id=delivery.user_id, device=device, payload=result)
    now = utcnow()
    delivery.status = "completed"
    delivery.completed_at = now
    delivery.updated_at = now
    delivery.revision += 1
    delivery.completion_event_id = event_id
    delivery.completion_payload_hash = request_hash
    delivery.training_session_id = session.id
    db.session.flush()
    _record_delivery_change(delivery)
    return session, duplicate


def active_deliveries(user_id, device_id, limit=20):
    return db.session.execute(
        db.select(CompanionWorkoutDelivery).where(
            CompanionWorkoutDelivery.user_id == user_id,
            CompanionWorkoutDelivery.api_device_id == device_id,
        ).order_by(CompanionWorkoutDelivery.updated_at.desc()).limit(limit)
    ).scalars().all()
