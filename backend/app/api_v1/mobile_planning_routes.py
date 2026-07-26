from flask import current_app, g, request

from app.api_v1 import api_v1_bp
from app.api_v1.decorators import bearer_required
from app.api_v1.errors import success
from app.api_v1.schemas import json_body
from app.extensions import db
from app.services.mobile_planning import (
    _owned_workout,
    create_plan,
    create_workout,
    duplicate_plan,
    duplicate_workout,
    exercise_catalog,
    list_plans,
    patch_plan,
    patch_workout,
    plan_detail,
    schedule_workout,
    serialize_plan,
    serialize_workout,
)
from app.services.mobile_sync import (
    MobileSyncError,
    PlannedWorkoutService,
    claim_idempotency,
    finish_idempotency,
    rfc3339,
)


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


def _plan_summary(plan) -> dict:
    return {
        "public_id": plan.public_id,
        "status": plan.status,
        "revision": plan.revision,
        "active_version": plan.active_version_number if plan.workouts else None,
        "updated_at": rfc3339(plan.updated_at),
    }


def _workout_summary(workout) -> dict:
    return {
        "public_id": workout.public_id,
        "plan_id": workout.training_plan.public_id,
        "position": workout.position,
        "revision": workout.revision,
        "plan_revision": workout.training_plan.revision,
        "updated_at": rfc3339(workout.updated_at),
    }


@api_v1_bp.get("/mobile/exercises")
@bearer_required
def mobile_exercises():
    if request.args.get("muscle_group") or request.args.get("equipment"):
        raise MobileSyncError(
            "unsupported_filter",
            "El catálogo actual no contiene metadatos de músculo o equipo.",
        )
    return success(
        exercise_catalog(
            user_id=g.api_user.id,
            search=request.args.get("search"),
            limit=request.args.get("limit", 50, type=int),
            cursor=request.args.get("cursor"),
        )
    )


@api_v1_bp.get("/mobile/plans")
@bearer_required
def mobile_plans():
    return success({"items": list_plans(g.api_user.id, request.args.get("status", "active"))})


@api_v1_bp.post("/mobile/plans")
@bearer_required
def mobile_plan_create():
    payload = json_body()

    def execute():
        plan = create_plan(user_id=g.api_user.id, payload=payload, device_id=g.api_session.device_id)
        _audit("mobile_plan_created", "training_plan")
        return _plan_summary(plan), 201

    return _idempotent("mobile_plan_create", payload, execute)


@api_v1_bp.get("/mobile/plans/<public_id>")
@bearer_required
def mobile_plan_detail(public_id):
    return success(plan_detail(g.api_user.id, public_id))


@api_v1_bp.patch("/mobile/plans/<public_id>")
@bearer_required
def mobile_plan_patch(public_id):
    payload = json_body()

    def execute():
        plan = patch_plan(
            user_id=g.api_user.id,
            public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_plan_updated", "training_plan")
        return _plan_summary(plan), 200

    return _idempotent(f"mobile_plan_patch:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/plans/<public_id>/duplicate")
@bearer_required
def mobile_plan_duplicate(public_id):
    payload = json_body()

    def execute():
        plan = duplicate_plan(
            user_id=g.api_user.id,
            public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_plan_duplicated", "training_plan")
        return _plan_summary(plan), 201

    return _idempotent(f"mobile_plan_duplicate:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/plans/<public_id>/workouts")
@bearer_required
def mobile_workout_create(public_id):
    payload = json_body()

    def execute():
        workout = create_workout(
            user_id=g.api_user.id,
            plan_public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_workout_created", "training_plan")
        return _workout_summary(workout), 201

    return _idempotent(f"mobile_workout_create:{public_id}", payload, execute)


@api_v1_bp.get("/mobile/workouts/<public_id>")
@bearer_required
def mobile_workout_detail(public_id):
    return success(serialize_workout(_owned_workout(g.api_user.id, public_id)))


@api_v1_bp.patch("/mobile/workouts/<public_id>")
@bearer_required
def mobile_workout_patch(public_id):
    payload = json_body()

    def execute():
        workout = patch_workout(
            user_id=g.api_user.id,
            public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_workout_updated", "training_plan")
        return _workout_summary(workout), 200

    return _idempotent(f"mobile_workout_patch:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/workouts/<public_id>/duplicate")
@bearer_required
def mobile_workout_duplicate(public_id):
    payload = json_body()

    def execute():
        workout = duplicate_workout(
            user_id=g.api_user.id,
            public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_workout_duplicated", "training_plan")
        return _workout_summary(workout), 201

    return _idempotent(f"mobile_workout_duplicate:{public_id}", payload, execute)


@api_v1_bp.post("/mobile/workouts/<public_id>/schedule")
@bearer_required
def mobile_workout_schedule(public_id):
    payload = json_body()

    def execute():
        planned = schedule_workout(
            user_id=g.api_user.id,
            public_id=public_id,
            payload=payload,
            device_id=g.api_session.device_id,
        )
        _audit("mobile_workout_scheduled", "planned_workout")
        return {
            "public_id": planned.public_id,
            "status": planned.status,
            "revision": planned.revision,
            "scheduled_for_date": planned.scheduled_for_date.isoformat(),
            "timezone": planned.timezone,
        }, 201

    return _idempotent(f"mobile_workout_schedule:{public_id}", payload, execute)


@api_v1_bp.delete("/mobile/scheduled-workouts/<public_id>")
@bearer_required
def mobile_scheduled_workout_delete(public_id):
    payload = json_body()

    def execute():
        if (
            set(payload) != {"base_revision"}
            or isinstance(payload["base_revision"], bool)
            or not isinstance(payload["base_revision"], int)
        ):
            raise MobileSyncError("invalid_request", "Se requiere base_revision.")
        planned = PlannedWorkoutService.get_by_public_id(g.api_user.id, public_id)
        PlannedWorkoutService.tombstone(
            planned,
            base_revision=payload["base_revision"],
            device_id=g.api_session.device_id,
        )
        _audit("mobile_schedule_cancelled", "planned_workout")
        return {"public_id": planned.public_id, "deleted": True, "revision": planned.revision}, 200

    return _idempotent(f"mobile_schedule_delete:{public_id}", payload, execute)
