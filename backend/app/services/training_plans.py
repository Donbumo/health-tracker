import json
from typing import Any

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, UploadedFile


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
