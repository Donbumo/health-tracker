from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    UploadedFile,
)
from app.services.manual_json import generate_standard_json
from app.services.training_plans import get_active_version
from app.services.validation import validate_json_document


class TrainingSessionError(ValueError):
    pass


@dataclass
class PlannedDay:
    key: str
    plan: TrainingPlan
    version: TrainingPlanVersion
    week: dict[str, Any]
    day: dict[str, Any]

    @property
    def label(self) -> str:
        return (
            f"{self.plan.name} · semana {self.week['week_number']} · "
            f"día {self.day['day_number']}: {self.day['name']}"
        )


def list_planned_days(user_id: int, plan_id: int | None = None) -> list[PlannedDay]:
    statement = db.select(TrainingPlan).where(TrainingPlan.user_id == user_id)
    if plan_id is not None:
        statement = statement.where(TrainingPlan.id == plan_id)
    plans = db.session.execute(statement.order_by(TrainingPlan.name)).scalars()

    options = []
    for plan in plans:
        version = get_active_version(plan, user_id)
        for week_index, week in enumerate(version.content["data"]["weeks"]):
            for day_index, day in enumerate(week["days"]):
                if not day["exercises"]:
                    continue
                options.append(
                    PlannedDay(
                        key=f"{version.id}:{week_index}:{day_index}",
                        plan=plan,
                        version=version,
                        week=week,
                        day=day,
                    )
                )
    return options


def resolve_planned_day(key: str, user_id: int) -> PlannedDay:
    try:
        version_id, week_index, day_index = (int(part) for part in key.split(":"))
    except (AttributeError, TypeError, ValueError) as error:
        raise TrainingSessionError("Invalid planned day selection") from error

    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.id == version_id,
            TrainingPlanVersion.user_id == user_id,
        )
    ).scalar_one_or_none()
    if version is None or version.training_plan.user_id != user_id:
        raise TrainingSessionError("Planned day does not belong to this user")
    if version.training_plan.active_version_number != version.version_number:
        raise TrainingSessionError("The selected plan version is no longer active")

    try:
        week = version.content["data"]["weeks"][week_index]
        day = week["days"][day_index]
    except (IndexError, KeyError, TypeError) as error:
        raise TrainingSessionError("Planned day no longer exists") from error
    if not day["exercises"]:
        raise TrainingSessionError("A rest day cannot create a training session")

    return PlannedDay(
        key=key,
        plan=version.training_plan,
        version=version,
        week=week,
        day=day,
    )


def build_completed_workout_document(
    *,
    user_id: int,
    planned_day: PlannedDay,
    performed_at: datetime,
    exercises: list[dict[str, Any]],
    notes: str | None = None,
) -> dict[str, Any]:
    if performed_at.tzinfo is None or performed_at.utcoffset() is None:
        raise TrainingSessionError("performed_at must include a timezone")
    if planned_day.plan.user_id != user_id or planned_day.version.user_id != user_id:
        raise TrainingSessionError("Training plan does not belong to this user")
    if not exercises:
        raise TrainingSessionError("Complete at least one training set")

    planned_exercises = {
        exercise["exercise_order"]: exercise
        for exercise in planned_day.day["exercises"]
    }
    for exercise in exercises:
        planned_exercise = planned_exercises.get(exercise["planned_exercise_order"])
        if planned_exercise is None or planned_exercise["name"] != exercise["name"]:
            raise TrainingSessionError("Completed exercise does not match the plan")
        planned_sets = {item["set_number"] for item in planned_exercise["sets"]}
        if any(item["planned_set_number"] not in planned_sets for item in exercise["sets"]):
            raise TrainingSessionError("Completed set does not match the plan")

    data: dict[str, Any] = {
        "training_plan_id": planned_day.plan.id,
        "training_plan_version_id": planned_day.version.id,
        "performed_at": performed_at.isoformat(timespec="seconds"),
        "planned_week_number": planned_day.week["week_number"],
        "planned_day_number": planned_day.day["day_number"],
        "exercises": exercises,
    }
    if notes and notes.strip():
        data["notes"] = notes.strip()

    return {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def _existing_session(source_file_id: int, user_id: int) -> TrainingSession | None:
    return db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.source_file_id == source_file_id,
            TrainingSession.user_id == user_id,
        )
    ).scalar_one_or_none()


def import_completed_workout(
    document: dict[str, Any],
    source_file: UploadedFile,
    planned_day: PlannedDay,
    user_id: int,
) -> tuple[TrainingSession, bool]:
    existing = _existing_session(source_file.id, user_id)
    if existing:
        return existing, True

    validate_json_document(document, "completed_workout")
    if document["user_id"] != user_id or source_file.user_id != user_id:
        raise TrainingSessionError("Completed workout does not belong to this user")
    if document["source_type"] != "manual_generated":
        raise TrainingSessionError("Manual sessions require manual_generated source_type")
    if source_file.source_type != "manual_generated":
        raise TrainingSessionError("Session source file must be manually generated")

    data = document["data"]
    if data["training_plan_id"] != planned_day.plan.id:
        raise TrainingSessionError("Training plan association does not match")
    if data["training_plan_version_id"] != planned_day.version.id:
        raise TrainingSessionError("Training plan version association does not match")

    performed_at = datetime.fromisoformat(data["performed_at"])
    session = TrainingSession(
        user_id=user_id,
        training_plan_id=planned_day.plan.id,
        training_plan_version_id=planned_day.version.id,
        source_file_id=source_file.id,
        performed_at=performed_at,
        planned_week_number=data["planned_week_number"],
        planned_day_number=data["planned_day_number"],
        notes=data.get("notes"),
    )
    db.session.add(session)

    try:
        db.session.flush()
        for exercise_data in data["exercises"]:
            exercise = TrainingSessionExercise(
                user_id=user_id,
                training_session_id=session.id,
                exercise_order=exercise_data["exercise_order"],
                planned_exercise_order=exercise_data["planned_exercise_order"],
                name=exercise_data["name"],
                notes=exercise_data.get("notes"),
            )
            db.session.add(exercise)
            db.session.flush()
            for set_data in exercise_data["sets"]:
                db.session.add(
                    TrainingSet(
                        user_id=user_id,
                        training_session_exercise_id=exercise.id,
                        set_number=set_data["set_number"],
                        planned_set_number=set_data["planned_set_number"],
                        weight_kg=Decimal(str(set_data["weight_kg"])),
                        reps=set_data["reps"],
                        rir=(
                            Decimal(str(set_data["rir"]))
                            if set_data.get("rir") is not None
                            else None
                        ),
                        notes=set_data.get("notes"),
                    )
                )
        db.session.commit()
        return session, False
    except IntegrityError:
        db.session.rollback()
        existing = _existing_session(source_file.id, user_id)
        if existing:
            return existing, True
        raise


def create_manual_training_session(
    *,
    user_id: int,
    planned_day: PlannedDay,
    performed_at: datetime,
    exercises: list[dict[str, Any]],
    notes: str | None = None,
) -> tuple[TrainingSession, bool]:
    document = build_completed_workout_document(
        user_id=user_id,
        planned_day=planned_day,
        performed_at=performed_at,
        exercises=exercises,
        notes=notes,
    )
    filename = (
        f"completed_workout_plan_{planned_day.plan.id}_v{planned_day.version.version_number}_"
        f"{performed_at.strftime('%Y%m%dT%H%M%S%z')}.json"
    )
    source_file, _file_duplicate = generate_standard_json(
        document=document,
        schema_name="completed_workout",
        user_id=user_id,
        original_filename=filename,
    )
    return import_completed_workout(document, source_file, planned_day, user_id)


def _planned_day_for_session(session: TrainingSession) -> dict[str, Any]:
    content = session.training_plan_version.content
    for week in content["data"]["weeks"]:
        if week["week_number"] != session.planned_week_number:
            continue
        for day in week["days"]:
            if day["day_number"] == session.planned_day_number:
                return day
    raise RuntimeError("Session planned day is missing from its plan version")


def compare_plan_to_session(session: TrainingSession) -> dict[str, Any]:
    planned_day = _planned_day_for_session(session)
    actual_by_order = {
        exercise.planned_exercise_order: exercise for exercise in session.exercises
    }
    rows = []
    planned_set_count = 0
    actual_set_count = sum(len(exercise.sets) for exercise in session.exercises)

    for planned_exercise in planned_day["exercises"]:
        actual_exercise = actual_by_order.get(planned_exercise["exercise_order"])
        actual_sets = {
            item.planned_set_number: item
            for item in (actual_exercise.sets if actual_exercise else [])
        }
        for planned_set in planned_exercise["sets"]:
            planned_set_count += 1
            actual_set = actual_sets.get(planned_set["set_number"])
            target_reps = planned_set.get("reps")
            actual_reps = actual_set.reps if actual_set else None
            rows.append(
                {
                    "exercise_name": planned_exercise["name"],
                    "planned_set_number": planned_set["set_number"],
                    "target_reps": target_reps,
                    "actual_reps": actual_reps,
                    "reps_difference": (
                        actual_reps - target_reps
                        if actual_reps is not None and target_reps is not None
                        else None
                    ),
                    "performed": actual_set is not None,
                }
            )

    return {
        "planned_exercises": len(planned_day["exercises"]),
        "actual_exercises": len(session.exercises),
        "planned_sets": planned_set_count,
        "actual_sets": actual_set_count,
        "rows": rows,
    }
