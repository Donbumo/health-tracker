from datetime import date, timedelta

from flask import current_app, g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.mobile_health import (
    create_body_stat,
    create_food,
    create_nutrition_item,
    create_steps,
    delete_body_stat,
    delete_nutrition_item,
    delete_steps,
    duplicate_nutrition_item,
    health_progress,
    health_today,
    list_body_stats,
    list_foods,
    list_steps,
    patch_body_stat,
    patch_food,
    patch_nutrition_item,
    patch_steps,
    serialize_body_stat,
    serialize_food,
    serialize_nutrition_day,
    serialize_nutrition_item,
    serialize_step,
)
from app.services.mobile_sync import (
    MobileSyncError,
    claim_idempotency,
    finish_idempotency,
)


def _target_date(value: str | None, *, field="date") -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError as error:
        raise MobileSyncError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _audit(event: str, entity_type: str) -> None:
    current_app.logger.info(
        "api_event=%s user_public=%s device=%s entity_type=%s",
        event,
        g.api_user.public_id[:8],
        g.api_session.device.public_device_id[:8],
        entity_type,
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


@api_v1_bp.get("/mobile/health/today")
@bearer_required
def mobile_health_today():
    target = _target_date(request.args.get("date"))
    return success(health_today(g.api_user.id, target, request.args.get("timezone")))


@api_v1_bp.get("/mobile/health/progress")
@bearer_required
def mobile_health_progress():
    start = _target_date(request.args.get("from"), field="from")
    end = _target_date(request.args.get("to"), field="to")
    return success(health_progress(g.api_user.id, start, end, request.args.get("timezone")))


@api_v1_bp.get("/mobile/body-stats")
@bearer_required
def mobile_body_stats():
    return success(list_body_stats(
        g.api_user.id,
        limit=request.args.get("limit", 50, type=int),
        cursor=request.args.get("cursor"),
    ))


@api_v1_bp.post("/mobile/body-stats")
@bearer_required
def mobile_body_stat_create():
    payload = json_body()

    def execute():
        record = create_body_stat(g.api_user.id, payload)
        _audit("mobile_body_stat_created", "body_stat")
        return serialize_body_stat(record), 201

    return _idempotent("mobile_body_stat_create", payload, execute)


@api_v1_bp.patch("/mobile/body-stats/<public_id>")
@bearer_required
def mobile_body_stat_patch(public_id):
    payload = json_body()

    def execute():
        record = patch_body_stat(g.api_user.id, public_id, payload)
        _audit("mobile_body_stat_updated", "body_stat")
        return serialize_body_stat(record), 200

    return _idempotent(f"mobile_body_stat_patch:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/body-stats/<public_id>")
@bearer_required
def mobile_body_stat_delete(public_id):
    payload = json_body()

    def execute():
        result = delete_body_stat(g.api_user.id, public_id, payload)
        _audit("mobile_body_stat_deleted", "body_stat")
        return result, 200

    return _idempotent(f"mobile_body_stat_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/nutrition/days/<date_value>")
@bearer_required
def mobile_nutrition_day(date_value):
    return success(serialize_nutrition_day(g.api_user.id, _target_date(date_value)))


@api_v1_bp.post("/mobile/nutrition/entries")
@bearer_required
def mobile_nutrition_entry_create():
    payload = json_body()

    def execute():
        record = create_nutrition_item(g.api_user.id, payload)
        _audit("mobile_nutrition_entry_created", "nutrition_entry")
        return serialize_nutrition_item(record), 201

    return _idempotent("mobile_nutrition_entry_create", payload, execute)


@api_v1_bp.patch("/mobile/nutrition/entries/<public_id>")
@bearer_required
def mobile_nutrition_entry_patch(public_id):
    payload = json_body()

    def execute():
        record = patch_nutrition_item(g.api_user.id, public_id, payload)
        _audit("mobile_nutrition_entry_updated", "nutrition_entry")
        return serialize_nutrition_item(record), 200

    return _idempotent(f"mobile_nutrition_entry_patch:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/nutrition/entries/<public_id>/duplicate")
@bearer_required
def mobile_nutrition_entry_duplicate(public_id):
    payload = json_body()

    def execute():
        record = duplicate_nutrition_item(g.api_user.id, public_id, payload)
        _audit("mobile_nutrition_entry_duplicated", "nutrition_entry")
        return serialize_nutrition_item(record), 201

    return _idempotent(f"mobile_nutrition_entry_duplicate:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/nutrition/entries/<public_id>")
@bearer_required
def mobile_nutrition_entry_delete(public_id):
    payload = json_body()

    def execute():
        result = delete_nutrition_item(g.api_user.id, public_id, payload)
        _audit("mobile_nutrition_entry_deleted", "nutrition_entry")
        return result, 200

    return _idempotent(f"mobile_nutrition_entry_delete:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/foods")
@bearer_required
def mobile_foods():
    return success(list_foods(
        g.api_user.id,
        search=request.args.get("search"),
        limit=request.args.get("limit", 50, type=int),
        cursor=request.args.get("cursor"),
        include_archived=request.args.get("include_archived") == "true",
    ))


@api_v1_bp.post("/mobile/foods")
@bearer_required
def mobile_food_create():
    payload = json_body()

    def execute():
        record = create_food(g.api_user.id, payload)
        _audit("mobile_food_created", "food")
        return serialize_food(record), 201

    return _idempotent("mobile_food_create", payload, execute)


@api_v1_bp.patch("/mobile/foods/<public_id>")
@bearer_required
def mobile_food_patch(public_id):
    payload = json_body()

    def execute():
        record = patch_food(g.api_user.id, public_id, payload)
        _audit("mobile_food_updated", "food")
        return serialize_food(record), 200

    return _idempotent(f"mobile_food_patch:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/steps")
@bearer_required
def mobile_steps():
    today = date.today()
    start = _target_date(request.args.get("from", (today - timedelta(days=29)).isoformat()), field="from")
    end = _target_date(request.args.get("to", today.isoformat()), field="to")
    return success(list_steps(
        g.api_user.id,
        start=start,
        end=end,
        limit=request.args.get("limit", 100, type=int),
    ))


@api_v1_bp.post("/mobile/steps")
@bearer_required
def mobile_steps_create():
    payload = json_body()

    def execute():
        record = create_steps(g.api_user.id, payload)
        _audit("mobile_steps_created", "steps")
        return serialize_step(record), 201

    return _idempotent("mobile_steps_create", payload, execute)


@api_v1_bp.patch("/mobile/steps/<public_id>")
@bearer_required
def mobile_steps_patch(public_id):
    payload = json_body()

    def execute():
        record = patch_steps(g.api_user.id, public_id, payload)
        _audit("mobile_steps_updated", "steps")
        return serialize_step(record), 200

    return _idempotent(f"mobile_steps_patch:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/steps/<public_id>")
@bearer_required
def mobile_steps_delete(public_id):
    payload = json_body()

    def execute():
        result = delete_steps(g.api_user.id, public_id, payload)
        _audit("mobile_steps_deleted", "steps")
        return result, 200

    return _idempotent(f"mobile_steps_delete:{public_id}", payload, execute)
