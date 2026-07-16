from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import uuid
from pathlib import Path

from flask import current_app

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    UploadedFile,
    PlannedWorkout,
    WorkoutSessionDraft,
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


def resolve_planned_workout_day(
    planned_workout: PlannedWorkout, user_id: int
) -> PlannedDay:
    if planned_workout.user_id != user_id or planned_workout.deleted_at is not None:
        raise TrainingSessionError("Planned workout does not belong to this user")
    version = planned_workout.training_plan_version
    if version.user_id != user_id or version.training_plan_id != planned_workout.training_plan_id:
        raise TrainingSessionError("Planned workout plan version is invalid")
    snapshot = planned_workout.payload_snapshot_json
    week_number = snapshot.get("week_number")
    day_number = snapshot.get("day_number")
    for week_index, week in enumerate(version.content["data"]["weeks"]):
        if week["week_number"] != week_number:
            continue
        for day_index, day in enumerate(week["days"]):
            if day["day_number"] == day_number and day.get("exercises"):
                return PlannedDay(
                    key=f"{version.id}:{week_index}:{day_index}",
                    plan=planned_workout.training_plan,
                    version=version,
                    week=week,
                    day=day,
                )
    raise TrainingSessionError("Planned workout day no longer exists")


def resolve_session_planned_day(
    session: TrainingSession, user_id: int
) -> PlannedDay:
    """Resolve the immutable plan-version day used by an existing session."""
    if session.user_id != user_id:
        raise TrainingSessionError("Training session does not belong to this user")
    version = session.training_plan_version
    plan = session.training_plan
    if (
        version.user_id != user_id
        or plan.user_id != user_id
        or version.training_plan_id != plan.id
    ):
        raise TrainingSessionError("Training session plan version is invalid")
    for week_index, week in enumerate(version.content["data"]["weeks"]):
        if week["week_number"] != session.planned_week_number:
            continue
        for day_index, day in enumerate(week["days"]):
            if (
                day["day_number"] == session.planned_day_number
                and day.get("exercises")
            ):
                return PlannedDay(
                    key=f"{version.id}:{week_index}:{day_index}",
                    plan=plan,
                    version=version,
                    week=week,
                    day=day,
                )
    raise TrainingSessionError("Training session planned day no longer exists")


def build_completed_workout_document(
    *,
    user_id: int,
    planned_day: PlannedDay,
    performed_at: datetime,
    exercises: list[dict[str, Any]],
    duration_seconds: int | None = None,
    average_heart_rate_bpm: int | None = None,
    calories_burned: Decimal | float | int | None = None,
    notes: str | None = None,
    client_submission_id: str | None = None,
) -> dict[str, Any]:
    if performed_at.tzinfo is None or performed_at.utcoffset() is None:
        raise TrainingSessionError("performed_at must include a timezone")
    if planned_day.plan.user_id != user_id or planned_day.version.user_id != user_id:
        raise TrainingSessionError("Training plan does not belong to this user")
    if not exercises:
        raise TrainingSessionError("Complete at least one training set")

    _validate_completed_exercises(exercises, planned_day)

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
    if duration_seconds is not None:
        data["duration_seconds"] = duration_seconds
    if average_heart_rate_bpm is not None:
        data["average_heart_rate_bpm"] = average_heart_rate_bpm
    if calories_burned is not None:
        data["calories_burned"] = float(calories_burned)
    if client_submission_id is not None:
        try:
            data["client_submission_id"] = str(uuid.UUID(client_submission_id))
        except (TypeError, ValueError) as error:
            raise TrainingSessionError(
                "client_submission_id must be a UUID"
            ) from error

    return {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def _validate_completed_exercises(
    exercises: list[dict[str, Any]],
    planned_day: PlannedDay,
) -> None:
    if len({item["exercise_order"] for item in exercises}) != len(exercises):
        raise TrainingSessionError("Completed exercise order must be unique")
    if len({item["planned_exercise_order"] for item in exercises}) != len(exercises):
        raise TrainingSessionError("Planned exercise order must be unique")

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
        set_numbers = [item["set_number"] for item in exercise["sets"]]
        if len(set(set_numbers)) != len(set_numbers):
            raise TrainingSessionError("Completed set numbers must be unique")


def _existing_session(source_file_id: int, user_id: int) -> TrainingSession | None:
    return db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.source_file_id == source_file_id,
            TrainingSession.user_id == user_id,
        )
    ).scalar_one_or_none()


def _existing_submission(
    client_submission_id: str, user_id: int
) -> TrainingSession | None:
    return db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.client_submission_id == client_submission_id,
            TrainingSession.user_id == user_id,
        )
    ).scalar_one_or_none()


def import_completed_workout(
    document: dict[str, Any],
    source_file: UploadedFile,
    planned_day: PlannedDay,
    user_id: int,
    *,
    client_submission_id: str | None = None,
    submission_payload_hash: str | None = None,
    planned_workout: PlannedWorkout | None = None,
    preferred_load_unit: str | None = None,
    remembered_profiles: list[dict[str, Any]] | None = None,
) -> tuple[TrainingSession, bool]:
    if client_submission_id is not None:
        existing_submission = _existing_submission(client_submission_id, user_id)
        if existing_submission is not None:
            if existing_submission.client_payload_sha256 == submission_payload_hash:
                return existing_submission, True
            raise TrainingSessionError(
                "submission_conflict: this submission ID already has different data"
            )
    existing = _existing_session(source_file.id, user_id)
    if existing:
        return existing, True

    validate_json_document(document, "completed_workout")
    try:
        from app.services.workout_loads import validate_completed_workout_loads

        validate_completed_workout_loads(document)
    except ValueError as error:
        raise TrainingSessionError(str(error)) from error
    if document["user_id"] != user_id or source_file.user_id != user_id:
        raise TrainingSessionError("Completed workout does not belong to this user")
    if source_file.source_type not in {"manual_generated", "uploaded"}:
        raise TrainingSessionError("Unsupported session source file type")
    if (
        source_file.source_type == "manual_generated"
        and document["source_type"] != "manual_generated"
    ):
        raise TrainingSessionError("Generated sessions require manual_generated source_type")

    data = document["data"]
    if data["training_plan_id"] != planned_day.plan.id:
        raise TrainingSessionError("Training plan association does not match")
    if data["training_plan_version_id"] != planned_day.version.id:
        raise TrainingSessionError("Training plan version association does not match")
    if data["planned_week_number"] != planned_day.week["week_number"]:
        raise TrainingSessionError("Planned week association does not match")
    if data["planned_day_number"] != planned_day.day["day_number"]:
        raise TrainingSessionError("Planned day association does not match")
    _validate_completed_exercises(data["exercises"], planned_day)

    locked_planned = None
    if planned_workout is not None:
        locked_planned = db.session.execute(
            db.select(PlannedWorkout)
            .where(
                PlannedWorkout.id == planned_workout.id,
                PlannedWorkout.user_id == user_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if locked_planned is None:
            raise TrainingSessionError("Planned workout does not belong to this user")
        if (
            locked_planned.training_plan_id != planned_day.plan.id
            or locked_planned.training_plan_version_id != planned_day.version.id
        ):
            raise TrainingSessionError(
                "Planned workout does not match the selected plan version"
            )
        if locked_planned.status not in {"planned", "in_progress", "skipped"}:
            raise TrainingSessionError(
                "submission_conflict: planned workout already finished"
            )

    performed_at = datetime.fromisoformat(data["performed_at"])
    session = TrainingSession(
        user_id=user_id,
        training_plan_id=planned_day.plan.id,
        training_plan_version_id=planned_day.version.id,
        source_file_id=source_file.id,
        planned_workout_id=locked_planned.id if locked_planned else None,
        client_submission_id=client_submission_id,
        client_payload_sha256=submission_payload_hash,
        performed_at=performed_at,
        planned_week_number=data["planned_week_number"],
        planned_day_number=data["planned_day_number"],
        duration_seconds=data.get("duration_seconds"),
        average_heart_rate_bpm=data.get("average_heart_rate_bpm"),
        calories_burned=(
            Decimal(str(data["calories_burned"]))
            if data.get("calories_burned") is not None
            else None
        ),
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
                from app.services.workout_loads import validate_load_details

                db.session.add(
                    TrainingSet(
                        user_id=user_id,
                        training_session_exercise_id=exercise.id,
                        set_number=set_data["set_number"],
                        planned_set_number=set_data["planned_set_number"],
                        weight_kg=Decimal(str(set_data["weight_kg"])),
                        load_details_json=validate_load_details(
                            set_data["weight_kg"], set_data.get("load_details")
                        ),
                        reps=set_data["reps"],
                        rir=(
                            Decimal(str(set_data["rir"]))
                            if set_data.get("rir") is not None
                            else None
                        ),
                        rpe=(
                            Decimal(str(set_data["rpe"]))
                            if set_data.get("rpe") is not None
                            else None
                        ),
                        rest_seconds=set_data.get("rest_seconds"),
                        notes=set_data.get("notes"),
                    )
                )
        db.session.flush()
        if locked_planned is not None:
            from app.services.mobile_sync import (
                PlannedWorkoutService,
                record_sync_change,
                serialize_completed_workout,
            )

            locked_planned.status = "completed"
            locked_planned.completed_at = performed_at
            PlannedWorkoutService._touch(locked_planned, None)
            session.planned_workout = locked_planned
        if client_submission_id is not None:
            from app.services.mobile_sync import (
                record_sync_change,
                serialize_completed_workout,
            )

            db.session.flush()
            record_sync_change(
                user_id=user_id,
                entity_type="completed_workout",
                entity_public_id=session.public_id,
                operation="upsert",
                revision=session.revision,
                payload=serialize_completed_workout(session),
                device_id=None,
            )
            draft = db.session.execute(
                db.select(WorkoutSessionDraft).where(
                    WorkoutSessionDraft.user_id == user_id,
                    WorkoutSessionDraft.client_submission_id
                    == client_submission_id,
                )
            ).scalar_one_or_none()
            if draft is not None:
                db.session.delete(draft)
        if preferred_load_unit is not None:
            from app.models import User

            if preferred_load_unit not in {"kg", "lb"}:
                raise TrainingSessionError("Unsupported preferred load unit")
            user = db.session.get(User, user_id)
            if user is None:
                raise TrainingSessionError("User not found")
            user.preferred_load_unit = preferred_load_unit
        if remembered_profiles:
            from app.services.workout_loads import upsert_exercise_load_profile

            for profile in remembered_profiles:
                upsert_exercise_load_profile(
                    user_id=user_id,
                    exercise_name=profile["exercise_name"],
                    load_details=profile["load_details"],
                )
        db.session.commit()
        return session, False
    except IntegrityError:
        db.session.rollback()
        existing = (
            _existing_submission(client_submission_id, user_id)
            if client_submission_id is not None
            else _existing_session(source_file.id, user_id)
        )
        if existing:
            if (
                client_submission_id is None
                or existing.client_payload_sha256 == submission_payload_hash
            ):
                return existing, True
            raise TrainingSessionError(
                "submission_conflict: this submission ID already has different data"
            )
        if planned_workout is not None:
            existing_planned_session = db.session.execute(
                db.select(TrainingSession).where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.planned_workout_id == planned_workout.id,
                )
            ).scalar_one_or_none()
            if existing_planned_session is not None:
                raise TrainingSessionError(
                    "submission_conflict: planned workout already finished"
                )
        raise
    except Exception:
        db.session.rollback()
        raise


def create_manual_training_session(
    *,
    user_id: int,
    planned_day: PlannedDay,
    performed_at: datetime,
    exercises: list[dict[str, Any]],
    duration_seconds: int | None = None,
    average_heart_rate_bpm: int | None = None,
    calories_burned: Decimal | float | int | None = None,
    notes: str | None = None,
    client_submission_id: str | None = None,
    planned_workout: PlannedWorkout | None = None,
    preferred_load_unit: str | None = None,
    remembered_profiles: list[dict[str, Any]] | None = None,
) -> tuple[TrainingSession, bool]:
    document = build_completed_workout_document(
        user_id=user_id,
        planned_day=planned_day,
        performed_at=performed_at,
        exercises=exercises,
        duration_seconds=duration_seconds,
        average_heart_rate_bpm=average_heart_rate_bpm,
        calories_burned=calories_burned,
        notes=notes,
        client_submission_id=client_submission_id,
    )
    from app.services.mobile_sync import canonical_hash

    submission_payload_hash = canonical_hash(document)
    if client_submission_id is not None:
        existing = _existing_submission(client_submission_id, user_id)
        if existing is not None:
            if existing.client_payload_sha256 == submission_payload_hash:
                draft = db.session.execute(
                    db.select(WorkoutSessionDraft).where(
                        WorkoutSessionDraft.user_id == user_id,
                        WorkoutSessionDraft.client_submission_id
                        == client_submission_id,
                    )
                ).scalar_one_or_none()
                if draft is not None:
                    db.session.delete(draft)
                    db.session.commit()
                return existing, True
            raise TrainingSessionError(
                "submission_conflict: this submission ID already has different data"
            )
    filename = (
        f"completed_workout_plan_{planned_day.plan.id}_v{planned_day.version.version_number}_"
        f"{performed_at.strftime('%Y%m%dT%H%M%S%z')}.json"
    )
    source_file, file_duplicate = generate_standard_json(
        document=document,
        schema_name="completed_workout",
        user_id=user_id,
        original_filename=filename,
        commit=False,
    )
    stored_filename = source_file.stored_filename
    try:
        return import_completed_workout(
            document,
            source_file,
            planned_day,
            user_id,
            client_submission_id=client_submission_id,
            submission_payload_hash=submission_payload_hash,
            planned_workout=planned_workout,
            preferred_load_unit=preferred_load_unit,
            remembered_profiles=remembered_profiles,
        )
    except Exception:
        db.session.rollback()
        if not file_duplicate:
            generated_root = Path(current_app.config["GENERATED_UPLOAD_ROOT"]).resolve()
            candidate = (
                generated_root
                / f"user_{user_id}"
                / stored_filename
            ).resolve()
            try:
                candidate.relative_to(generated_root)
            except ValueError:
                pass
            else:
                candidate.unlink(missing_ok=True)
        raise


def update_manual_training_session(
    *,
    session: TrainingSession,
    user_id: int,
    planned_day: PlannedDay,
    performed_at: datetime,
    exercises: list[dict[str, Any]],
    duration_seconds: int | None = None,
    average_heart_rate_bpm: int | None = None,
    calories_burned: Decimal | float | int | None = None,
    notes: str | None = None,
    preferred_load_unit: str | None = None,
    remembered_profiles: list[dict[str, Any]] | None = None,
) -> tuple[TrainingSession, bool]:
    """Update one owned manual session while preserving stable row identities."""
    if session.user_id != user_id:
        raise TrainingSessionError("Training session does not belong to this user")
    if (
        session.training_plan_id != planned_day.plan.id
        or session.training_plan_version_id != planned_day.version.id
    ):
        raise TrainingSessionError("Training session plan version cannot be changed")
    document = build_completed_workout_document(
        user_id=user_id,
        planned_day=planned_day,
        performed_at=performed_at,
        exercises=exercises,
        duration_seconds=duration_seconds,
        average_heart_rate_bpm=average_heart_rate_bpm,
        calories_burned=calories_burned,
        notes=notes,
        client_submission_id=session.client_submission_id,
    )
    from app.services.mobile_sync import canonical_hash

    payload_hash = canonical_hash(document)
    if session.client_payload_sha256 == payload_hash:
        return session, True
    filename = (
        f"completed_workout_edit_{session.public_id}_r{session.revision + 1}.json"
    )
    source_file, file_duplicate = generate_standard_json(
        document=document,
        schema_name="completed_workout",
        user_id=user_id,
        original_filename=filename,
        commit=False,
    )
    stored_filename = source_file.stored_filename
    try:
        from app.models import User
        from app.services.mobile_sync import record_sync_change, serialize_completed_workout
        from app.services.workout_loads import (
            upsert_exercise_load_profile,
            validate_load_details,
        )

        session.source_file = source_file
        session.performed_at = performed_at
        session.duration_seconds = duration_seconds
        session.average_heart_rate_bpm = average_heart_rate_bpm
        session.calories_burned = (
            Decimal(str(calories_burned)) if calories_burned is not None else None
        )
        session.notes = notes.strip() if notes and notes.strip() else None
        session.client_payload_sha256 = payload_hash
        session.revision += 1
        session.updated_at = datetime.now(timezone.utc)

        existing_exercises = {
            item.planned_exercise_order: item for item in session.exercises
        }
        incoming_orders = {item["planned_exercise_order"] for item in exercises}
        for planned_order, existing in existing_exercises.items():
            if planned_order not in incoming_orders:
                db.session.delete(existing)
        db.session.flush()
        for exercise_data in exercises:
            exercise = existing_exercises.get(exercise_data["planned_exercise_order"])
            if exercise is None:
                exercise = TrainingSessionExercise(
                    user_id=user_id,
                    training_session=session,
                    planned_exercise_order=exercise_data["planned_exercise_order"],
                )
                db.session.add(exercise)
                db.session.flush()
            exercise.exercise_order = exercise_data["exercise_order"]
            exercise.name = exercise_data["name"]
            exercise.notes = exercise_data.get("notes")
            existing_sets = {item.planned_set_number: item for item in exercise.sets}
            incoming_set_numbers = {
                item["planned_set_number"] for item in exercise_data["sets"]
            }
            for planned_set_number, existing_set in existing_sets.items():
                if planned_set_number not in incoming_set_numbers:
                    db.session.delete(existing_set)
            db.session.flush()
            for set_data in exercise_data["sets"]:
                training_set = existing_sets.get(set_data["planned_set_number"])
                if training_set is None:
                    training_set = TrainingSet(
                        user_id=user_id,
                        session_exercise=exercise,
                        planned_set_number=set_data["planned_set_number"],
                    )
                    db.session.add(training_set)
                training_set.set_number = set_data["set_number"]
                training_set.weight_kg = Decimal(str(set_data["weight_kg"]))
                training_set.load_details_json = validate_load_details(
                    set_data["weight_kg"], set_data.get("load_details")
                )
                training_set.reps = set_data["reps"]
                training_set.rir = (
                    Decimal(str(set_data["rir"]))
                    if set_data.get("rir") is not None
                    else None
                )
                training_set.rpe = (
                    Decimal(str(set_data["rpe"]))
                    if set_data.get("rpe") is not None
                    else None
                )
                training_set.rest_seconds = set_data.get("rest_seconds")
                training_set.notes = set_data.get("notes")

        if preferred_load_unit is not None:
            if preferred_load_unit not in {"kg", "lb"}:
                raise TrainingSessionError("Unsupported preferred load unit")
            db.session.get(User, user_id).preferred_load_unit = preferred_load_unit
        for profile in remembered_profiles or []:
            upsert_exercise_load_profile(
                user_id=user_id,
                exercise_name=profile["exercise_name"],
                load_details=profile["load_details"],
            )
        db.session.flush()
        db.session.expire(session, ["exercises"])
        record_sync_change(
            user_id=user_id,
            entity_type="completed_workout",
            entity_public_id=session.public_id,
            operation="upsert",
            revision=session.revision,
            payload=serialize_completed_workout(session),
            device_id=None,
        )
        db.session.commit()
        return session, False
    except Exception:
        db.session.rollback()
        if not file_duplicate:
            generated_root = Path(current_app.config["GENERATED_UPLOAD_ROOT"]).resolve()
            candidate = (
                generated_root / f"user_{user_id}" / stored_filename
            ).resolve()
            try:
                candidate.relative_to(generated_root)
            except ValueError:
                pass
            else:
                candidate.unlink(missing_ok=True)
        raise


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
            target_reps_min = planned_set.get("reps_min", target_reps)
            target_reps_max = planned_set.get("reps_max", target_reps)
            actual_reps = actual_set.reps if actual_set else None
            reps_difference = None
            if actual_reps is not None and target_reps_min is not None:
                if actual_reps < target_reps_min:
                    reps_difference = actual_reps - target_reps_min
                elif actual_reps > target_reps_max:
                    reps_difference = actual_reps - target_reps_max
                else:
                    reps_difference = 0
            rows.append(
                {
                    "exercise_name": planned_exercise["name"],
                    "planned_set_number": planned_set["set_number"],
                    "target_reps": target_reps,
                    "target_reps_min": target_reps_min,
                    "target_reps_max": target_reps_max,
                    "actual_reps": actual_reps,
                    "reps_difference": reps_difference,
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
