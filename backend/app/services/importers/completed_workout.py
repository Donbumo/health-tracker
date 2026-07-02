from app.extensions import db
from app.models import TrainingPlanVersion, TrainingSession, UploadedFile
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import validate_json_document
from app.services.workout_sessions import (
    PlannedDay,
    TrainingSessionError,
    import_completed_workout,
)


def _existing_session(source_file_id: int, user_id: int) -> TrainingSession | None:
    return db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.source_file_id == source_file_id,
            TrainingSession.user_id == user_id,
        )
    ).scalar_one_or_none()


def _resolve_planned_day(document: dict, user_id: int) -> PlannedDay:
    data = document["data"]
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.id == data["training_plan_version_id"],
            TrainingPlanVersion.training_plan_id == data["training_plan_id"],
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    if version is None or version.training_plan.user_id != user_id:
        raise TrainingSessionError("Training plan version does not belong to this user")

    week = next(
        (
            item
            for item in version.content["data"]["weeks"]
            if item["week_number"] == data["planned_week_number"]
        ),
        None,
    )
    if week is None:
        raise TrainingSessionError("Planned week does not exist in this plan version")
    day = next(
        (
            item
            for item in week["days"]
            if item["day_number"] == data["planned_day_number"]
        ),
        None,
    )
    if day is None or not day["exercises"]:
        raise TrainingSessionError("Planned training day does not exist")
    return PlannedDay(
        key=f"import:{version.id}:{week['week_number']}:{day['day_number']}",
        plan=version.training_plan,
        version=version,
        week=week,
        day=day,
    )


def import_completed_workout_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[TrainingSession, bool]:
    if source_file.user_id != user_id:
        raise TrainingSessionError("Completed workout does not belong to this user")
    existing = _existing_session(source_file.id, user_id)
    if existing:
        return existing, True
    if source_file.source_type != "uploaded":
        raise ImporterError("Completed workout imports require an uploaded source file")

    document = load_json_source(source_file, user_id)
    validate_json_document(document, "completed_workout")
    if document["user_id"] != user_id:
        raise TrainingSessionError("Completed workout does not belong to this user")
    planned_day = _resolve_planned_day(document, user_id)
    return import_completed_workout(document, source_file, planned_day, user_id)
