import hashlib
import json
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, UploadedFile
from app.services.validation import validate_json_document


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


def _source_file_path(source_file: UploadedFile, user_id: int) -> Path:
    if source_file.user_id != user_id:
        raise TrainingPlanImportError("Source file does not belong to this user")
    if source_file.source_type != "uploaded":
        raise TrainingPlanImportError("Training plans must originate from an upload")

    data_root = Path(current_app.config["DATA_ROOT"]).resolve()
    source_path = (data_root / source_file.storage_path).resolve()
    if not source_path.is_relative_to(data_root):
        raise TrainingPlanImportError("Source file path is outside DATA_ROOT")
    if not source_path.is_file():
        raise TrainingPlanImportError("Source file is missing")
    return source_path


def _existing_plan(source_file_id: int, user_id: int) -> TrainingPlan | None:
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.source_file_id == source_file_id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    return version.training_plan if version else None


def import_training_plan(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[TrainingPlan, bool]:
    existing = _existing_plan(source_file.id, user_id)
    if existing:
        return existing, True

    source_path = _source_file_path(source_file, user_id)
    try:
        document = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrainingPlanImportError("The uploaded file is not valid UTF-8 JSON") from error

    if not isinstance(document, dict):
        raise TrainingPlanImportError("The training plan JSON must be an object")

    validate_json_document(document, "training_plan")
    if document["user_id"] != user_id:
        raise TrainingPlanImportError("Document user_id does not match its owner")
    if document["source_type"] != "uploaded":
        raise TrainingPlanImportError("Imported plans require uploaded source_type")
    _validate_plan_ordering(document)

    name = document["data"]["name"].strip()
    if not name:
        raise TrainingPlanImportError("Training plan name must not be blank")
    description = document["data"].get("description")
    if description is not None:
        description = description.strip() or None

    canonical_bytes = serialize_training_plan(document)
    content_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    plan = TrainingPlan(
        user_id=user_id,
        name=name,
        description=description,
        active_version_number=1,
    )
    db.session.add(plan)

    try:
        db.session.flush()
        version = TrainingPlanVersion(
            user_id=user_id,
            training_plan_id=plan.id,
            version_number=1,
            source_file_id=source_file.id,
            schema_version=document["schema_version"],
            sha256=content_sha256,
            content=document,
        )
        db.session.add(version)
        db.session.commit()
        return plan, False
    except IntegrityError:
        db.session.rollback()
        existing = _existing_plan(source_file.id, user_id)
        if existing:
            return existing, True
        raise


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
