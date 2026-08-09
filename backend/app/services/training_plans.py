import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, UploadedFile


class TrainingPlanImportError(ValueError):
    pass


def _require_unique_numbers(items: list[dict[str, Any]], field: str, label: str) -> None:
    values = [item[field] for item in items]
    if len(values) != len(set(values)):
        raise TrainingPlanImportError(f"{label} numbers must be unique")


def _validate_plan_ordering(document: dict[str, Any]) -> None:
    weeks = document["data"]["weeks"]
    _require_unique_numbers(weeks, "week_number", "Week")
    for week in weeks:
        _require_unique_numbers(week["days"], "day_number", "Day")
        for day in week["days"]:
            _require_unique_numbers(
                day["exercises"],
                "exercise_order",
                "Exercise order",
            )
            for exercise in day["exercises"]:
                _require_unique_numbers(exercise["sets"], "set_number", "Set")
                for planned_set in exercise["sets"]:
                    if (
                        planned_set.get("reps_min") is not None
                        and planned_set["reps_min"] > planned_set["reps_max"]
                    ):
                        raise TrainingPlanImportError(
                            "Set reps_min must not exceed reps_max"
                        )


def serialize_training_plan(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def import_training_plan(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[TrainingPlan, bool]:
    """Compatibility wrapper for the Phase 3 public service function."""
    from app.services.importers.training_plan import import_training_plan_file

    return import_training_plan_file(source_file, user_id)


def get_active_version(plan: TrainingPlan, user_id: int) -> TrainingPlanVersion:
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.version_number == plan.active_version_number,
        )
    ).scalar_one_or_none()
    if version is None:
        raise RuntimeError("Training plan active version is missing")
    return version


def replace_mobile_workouts_from_document(
    plan: TrainingPlan,
    document: dict[str, Any],
    user_id: int,
) -> None:
    """Refresh the mutable mobile editor projection from an immutable plan version."""
    if plan.user_id != user_id:
        raise TrainingPlanImportError("Training plan does not belong to this user")
    db.session.execute(
        db.delete(TrainingPlanWorkout).where(
            TrainingPlanWorkout.training_plan_id == plan.id,
            TrainingPlanWorkout.user_id == user_id,
        )
    )
    position = 0
    for week in document["data"]["weeks"]:
        for day in week["days"]:
            position += 1
            exercises = json.loads(json.dumps(day.get("exercises", [])))
            for exercise in exercises:
                exercise.setdefault("id", str(uuid.uuid4()))
                for planned_set in exercise.get("sets", []):
                    planned_set.setdefault("id", str(uuid.uuid4()))
            db.session.add(
                TrainingPlanWorkout(
                    public_id=str(uuid.uuid4()),
                    user_id=user_id,
                    training_plan_id=plan.id,
                    name=day["name"],
                    notes=day.get("notes"),
                    position=position,
                    exercises_json=exercises,
                )
            )


def list_training_plan_versions(
    plan: TrainingPlan,
    user_id: int,
) -> list[TrainingPlanVersion]:
    if plan.user_id != user_id:
        raise TrainingPlanImportError("Training plan does not belong to this user")
    return db.session.execute(
        db.select(TrainingPlanVersion)
        .where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == user_id,
        )
        .order_by(TrainingPlanVersion.version_number.desc())
    ).scalars().all()


def get_training_plan_version(
    plan: TrainingPlan,
    version_id: int,
    user_id: int,
) -> TrainingPlanVersion:
    if plan.user_id != user_id:
        raise TrainingPlanImportError("Training plan does not belong to this user")
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.id == version_id,
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    if version is None:
        raise TrainingPlanImportError("Training plan version does not exist")
    return version


def create_training_plan_version(
    *,
    plan: TrainingPlan,
    source_file: UploadedFile,
    user_id: int,
    change_reason: str,
) -> tuple[TrainingPlanVersion, bool]:
    if plan.user_id != user_id:
        raise TrainingPlanImportError("Training plan does not belong to this user")
    reason = (change_reason or "").strip()
    if len(reason) < 3 or len(reason) > 2000:
        raise TrainingPlanImportError(
            "Change reason must contain between 3 and 2000 characters"
        )

    used_source = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.source_file_id == source_file.id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    if used_source is not None:
        if used_source.training_plan_id == plan.id:
            return used_source, True
        raise TrainingPlanImportError(
            "The uploaded source file already belongs to another training plan"
        )

    from app.services.importers.training_plan import load_training_plan_document

    document = load_training_plan_document(source_file, user_id)
    canonical_bytes = serialize_training_plan(document)
    content_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    duplicate = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == user_id,
            TrainingPlanVersion.sha256 == content_sha256,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return duplicate, True

    locked_plan = db.session.execute(
        db.select(TrainingPlan)
        .where(TrainingPlan.id == plan.id, TrainingPlan.user_id == user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if locked_plan is None:
        raise TrainingPlanImportError("Training plan does not belong to this user")
    latest_number = db.session.execute(
        db.select(db.func.max(TrainingPlanVersion.version_number)).where(
            TrainingPlanVersion.training_plan_id == locked_plan.id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan_id=locked_plan.id,
        version_number=(latest_number or 0) + 1,
        source_file_id=source_file.id,
        created_by_user_id=user_id,
        change_reason=reason,
        schema_version=document["schema_version"],
        sha256=content_sha256,
        content=document,
    )
    locked_plan.updated_at = datetime.now(timezone.utc)
    db.session.add(version)

    try:
        db.session.commit()
        return version, False
    except IntegrityError as error:
        db.session.rollback()
        duplicate = db.session.execute(
            db.select(TrainingPlanVersion).where(
                TrainingPlanVersion.training_plan_id == plan.id,
                TrainingPlanVersion.user_id == user_id,
                TrainingPlanVersion.sha256 == content_sha256,
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            return duplicate, True
        raise TrainingPlanImportError("Could not assign the next version number") from error


def activate_training_plan_version(
    *,
    plan: TrainingPlan,
    version_id: int,
    user_id: int,
) -> TrainingPlanVersion:
    version = get_training_plan_version(plan, version_id, user_id)
    plan.active_version_number = version.version_number
    plan.name = version.content["data"]["name"].strip()
    description = version.content["data"].get("description")
    plan.description = description.strip() or None if description is not None else None
    plan.updated_at = datetime.now(timezone.utc)
    replace_mobile_workouts_from_document(plan, version.content, user_id)
    db.session.commit()
    return version
