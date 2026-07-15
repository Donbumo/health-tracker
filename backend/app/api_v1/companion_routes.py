import uuid
from datetime import datetime, timezone

from flask import current_app, g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.companion import (
    SERVER_CAPABILITIES,
    active_deliveries,
    add_progress,
    complete_delivery,
    get_profile,
    negotiate_profile,
    owned_delivery,
    prepare_delivery,
    serialize_delivery,
    serialize_profile,
    serialize_progress,
    transition_delivery,
)
from app.services.mobile_sync import (
    MobileSyncError,
    claim_idempotency,
    finish_idempotency,
    parse_rfc3339,
    serialize_completed_workout,
)


def _audit(event, *, delivery=None):
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s delivery=%s",
        event,
        g.api_user.public_id[:8],
        g.api_session.device.public_device_id[:8],
        delivery.public_id[:8] if delivery else "none",
    )


def _idempotent(operation, payload, handler):
    record, replay = claim_idempotency(
        user_id=g.api_user.id,
        device_id=g.api_session.device_id,
        raw_key=request.headers.get("Idempotency-Key", ""),
        operation=operation,
        payload=payload,
    )
    if replay:
        return success(record.response_body_json, status=record.response_status)
    try:
        data, status = handler()
        finish_idempotency(record, data, status)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return success(data, status=status)


def _operation_payload(payload, allowed):
    if set(payload) != allowed or payload.get("schema_version") != "1.0":
        raise MobileSyncError("invalid_request", "La operación companion no es válida.")
    try:
        uuid.UUID(str(payload["client_operation_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_request", "client_operation_id debe ser UUID.") from error
    if not isinstance(payload.get("base_revision"), int) or payload["base_revision"] < 1:
        raise MobileSyncError("invalid_request", "base_revision no es válido.")


@api_v1_bp.get("/companion/profile")
@bearer_required
def companion_profile_get():
    return success(serialize_profile(get_profile(g.api_user.id, g.api_session.device_id)))


def _negotiate():
    try:
        profile, result = negotiate_profile(
            user_id=g.api_user.id,
            device=g.api_session.device,
            payload=json_body(),
        )
    except MobileSyncError:
        _audit("companion_protocol_rejected")
        raise
    db.session.commit()
    _audit("companion_profile_negotiated")
    return success(result, status=200 if profile.revision > 1 else 201)


@api_v1_bp.put("/companion/profile")
@bearer_required
def companion_profile_put():
    return _negotiate()


@api_v1_bp.post("/companion/negotiate")
@bearer_required
def companion_negotiate():
    return _negotiate()


@api_v1_bp.post("/companion/deliveries")
@bearer_required
def companion_delivery_create():
    payload = json_body()
    allowed = {"schema_version", "planned_workout_id", "expires_at"}
    if set(payload) - allowed or payload.get("schema_version") != "1.0" or not payload.get("planned_workout_id"):
        raise MobileSyncError("invalid_request", "La solicitud de entrega no es válida.")
    expires_at = parse_rfc3339(payload["expires_at"], "expires_at") if payload.get("expires_at") else None
    if expires_at and expires_at <= datetime.now(timezone.utc):
        raise MobileSyncError("invalid_request", "expires_at debe estar en el futuro.")

    def execute():
        delivery, duplicate = prepare_delivery(
            user_id=g.api_user.id,
            device=g.api_session.device,
            planned_public_id=payload["planned_workout_id"],
            mark_delivered=True,
            expires_at=expires_at,
        )
        _audit("companion_delivery_prepared", delivery=delivery)
        data = serialize_delivery(delivery)
        data["duplicate"] = duplicate
        return data, 200 if duplicate else 201

    return _idempotent("companion_delivery_create", payload, execute)


@api_v1_bp.get("/companion/deliveries")
@bearer_required
def companion_delivery_list():
    return success([
        serialize_delivery(item)
        for item in active_deliveries(g.api_user.id, g.api_session.device_id)
    ])


@api_v1_bp.get("/companion/deliveries/<public_id>")
@bearer_required
def companion_delivery_get(public_id):
    return success(serialize_delivery(owned_delivery(g.api_user.id, g.api_session.device_id, public_id)))


@api_v1_bp.get("/companion/deliveries/<public_id>/package")
@bearer_required
def companion_delivery_package(public_id):
    delivery = owned_delivery(g.api_user.id, g.api_session.device_id, public_id)
    return success(delivery.payload_snapshot_json)


def _transition(public_id, action):
    payload = json_body()
    fields = {"schema_version", "client_operation_id", "base_revision"}
    if action == "ack":
        fields |= {"received_at", "package_hash"}
    elif action in {"abort", "fail"}:
        fields |= {"reason_code"}
    _operation_payload(payload, fields)
    if action == "ack":
        parse_rfc3339(payload["received_at"], "received_at")

    def execute():
        delivery = owned_delivery(g.api_user.id, g.api_session.device_id, public_id, lock=True)
        try:
            transition_delivery(
                delivery,
                action=action,
                base_revision=payload["base_revision"],
                package_hash=payload.get("package_hash"),
                failure_code=payload.get("reason_code"),
            )
        except MobileSyncError as error:
            if error.code == "package_hash_mismatch":
                _audit("companion_package_hash_mismatch", delivery=delivery)
            raise
        event = {
            "ack": "companion_delivery_acknowledged",
            "start": "companion_delivery_started",
            "abort": "companion_delivery_aborted",
            "fail": "companion_delivery_failed",
        }[action]
        _audit(event, delivery=delivery)
        return serialize_delivery(delivery), 200

    return _idempotent(f"companion_delivery_{action}:{public_id}", payload, execute)


@api_v1_bp.post("/companion/deliveries/<public_id>/ack")
@bearer_required
def companion_delivery_ack(public_id):
    return _transition(public_id, "ack")


@api_v1_bp.post("/companion/deliveries/<public_id>/start")
@bearer_required
def companion_delivery_start(public_id):
    return _transition(public_id, "start")


@api_v1_bp.post("/companion/deliveries/<public_id>/abort")
@bearer_required
def companion_delivery_abort(public_id):
    return _transition(public_id, "abort")


@api_v1_bp.post("/companion/deliveries/<public_id>/fail")
@bearer_required
def companion_delivery_fail(public_id):
    return _transition(public_id, "fail")


@api_v1_bp.post("/companion/deliveries/<public_id>/progress")
@bearer_required
def companion_delivery_progress(public_id):
    payload = json_body()

    def execute():
        delivery = owned_delivery(g.api_user.id, g.api_session.device_id, public_id, lock=True)
        event, duplicate = add_progress(delivery=delivery, device=g.api_session.device, payload=payload)
        _audit("companion_progress_received", delivery=delivery)
        data = serialize_progress(event)
        data["duplicate"] = duplicate
        return data, 200 if duplicate else 201

    return _idempotent(f"companion_progress:{public_id}", payload, execute)


@api_v1_bp.post("/companion/deliveries/<public_id>/complete")
@bearer_required
def companion_delivery_complete(public_id):
    payload = json_body()

    def execute():
        delivery = owned_delivery(g.api_user.id, g.api_session.device_id, public_id, lock=True)
        try:
            session, duplicate = complete_delivery(
                delivery=delivery, device=g.api_session.device, payload=payload
            )
        except MobileSyncError as error:
            if error.code == "package_hash_mismatch":
                _audit("companion_package_hash_mismatch", delivery=delivery)
            raise
        _audit("companion_delivery_completed", delivery=delivery)
        return {
            "delivery": serialize_delivery(delivery),
            "completed_workout": serialize_completed_workout(session),
            "duplicate": duplicate,
        }, 200 if duplicate else 201

    return _idempotent(f"companion_complete:{public_id}", payload, execute)
