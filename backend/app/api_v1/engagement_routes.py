from datetime import date

from flask import current_app, g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.engagement import (
    adherence_summary,
    adherence_timeline,
    archive_goal,
    create_event,
    create_goal,
    create_rule,
    delete_rule,
    list_events,
    list_goals,
    list_rules,
    owned_goal,
    owned_rule,
    patch_goal,
    patch_rule,
    serialize_event,
    serialize_goal,
    serialize_rule,
    update_event,
)
from app.services.mobile_sync import MobileSyncError, claim_idempotency, finish_idempotency


def _audit(event: str, entity_type: str, state: str | None = None) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s entity_type=%s state=%s",
        event,
        g.api_user.public_id[:8],
        g.api_session.device.public_device_id[:8],
        entity_type,
        state or "none",
    )


def _idempotent(operation: str, payload: dict, handler):
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


def _query_date(name: str):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise MobileSyncError("invalid_date", f"{name} debe usar YYYY-MM-DD.") from error


@api_v1_bp.get("/mobile/goals")
@bearer_required
def mobile_goals():
    return success({"items": list_goals(
        g.api_user.id, include_archived=request.args.get("include_archived") == "true"
    )})


@api_v1_bp.post("/mobile/goals")
@bearer_required
def mobile_goal_create():
    payload = json_body()

    def execute():
        row = create_goal(g.api_user.id, payload)
        _audit("mobile_goal_created", "goal", row.state)
        return serialize_goal(row), 201

    return _idempotent("mobile_goal_create", payload, execute)


@api_v1_bp.get("/mobile/goals/<public_id>")
@bearer_required
def mobile_goal_detail(public_id):
    return success(serialize_goal(owned_goal(g.api_user.id, public_id)))


@api_v1_bp.patch("/mobile/goals/<public_id>")
@bearer_required
def mobile_goal_patch(public_id):
    payload = json_body()

    def execute():
        row = patch_goal(g.api_user.id, public_id, payload)
        _audit("mobile_goal_updated", "goal", row.state)
        return serialize_goal(row), 200

    return _idempotent(f"mobile_goal_patch:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/goals/<public_id>")
@bearer_required
def mobile_goal_delete(public_id):
    payload = json_body()

    def execute():
        row = archive_goal(g.api_user.id, public_id, payload)
        _audit("mobile_goal_archived", "goal", "archived")
        return serialize_goal(row), 200

    return _idempotent(f"mobile_goal_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/reminder-rules")
@bearer_required
def mobile_reminder_rules():
    return success({"items": list_rules(g.api_user.id)})


@api_v1_bp.post("/mobile/reminder-rules")
@bearer_required
def mobile_reminder_rule_create():
    payload = json_body()

    def execute():
        row = create_rule(g.api_user.id, payload)
        _audit("mobile_reminder_rule_created", "reminder_rule", "enabled" if row.enabled else "disabled")
        return serialize_rule(row), 201

    return _idempotent("mobile_reminder_rule_create", payload, execute)


@api_v1_bp.get("/mobile/reminder-rules/<public_id>")
@bearer_required
def mobile_reminder_rule_detail(public_id):
    return success(serialize_rule(owned_rule(g.api_user.id, public_id)))


@api_v1_bp.patch("/mobile/reminder-rules/<public_id>")
@bearer_required
def mobile_reminder_rule_patch(public_id):
    payload = json_body()

    def execute():
        row = patch_rule(g.api_user.id, public_id, payload)
        _audit("mobile_reminder_rule_updated", "reminder_rule", "enabled" if row.enabled else "disabled")
        return serialize_rule(row), 200

    return _idempotent(f"mobile_reminder_rule_patch:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/reminder-rules/<public_id>")
@bearer_required
def mobile_reminder_rule_delete(public_id):
    payload = json_body()

    def execute():
        result = delete_rule(g.api_user.id, public_id, payload)
        _audit("mobile_reminder_rule_deleted", "reminder_rule", "deleted")
        return result, 200

    return _idempotent(f"mobile_reminder_rule_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/reminder-events")
@bearer_required
def mobile_reminder_events():
    return success({"items": list_events(g.api_user.id, limit=request.args.get("limit", 50, type=int))})


@api_v1_bp.post("/mobile/reminder-events")
@bearer_required
def mobile_reminder_event_create():
    payload = json_body()

    def execute():
        row, replay = create_event(g.api_user, payload)
        _audit("mobile_reminder_event_recorded", "reminder_event", row.state)
        return serialize_event(row), 200 if replay else 201

    return _idempotent("mobile_reminder_event_create", payload, execute)


@api_v1_bp.patch("/mobile/reminder-events/<public_id>")
@bearer_required
def mobile_reminder_event_patch(public_id):
    payload = json_body()

    def execute():
        row = update_event(g.api_user.id, public_id, payload)
        _audit("mobile_reminder_event_updated", "reminder_event", row.state)
        return serialize_event(row), 200

    return _idempotent(f"mobile_reminder_event_patch:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/adherence/summary")
@bearer_required
def mobile_adherence_summary():
    return success(adherence_summary(
        g.api_user,
        days=request.args.get("days", 7, type=int),
        end=_query_date("to"),
        timezone_name=request.args.get("timezone"),
    ))


@api_v1_bp.get("/mobile/adherence/timeline")
@bearer_required
def mobile_adherence_timeline():
    return success(adherence_timeline(
        g.api_user,
        days=request.args.get("days", 7, type=int),
        end=_query_date("to"),
        timezone_name=request.args.get("timezone"),
    ))
