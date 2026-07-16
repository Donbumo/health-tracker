from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    Activity,
    ApiDevice,
    DailyEnergy,
    DailyNutrition,
    ExportRecord,
    ImportRun,
    MedicalLabReport,
    PlannedWorkout,
    TrainingSession,
    TrainingSessionExercise,
    WeighIn,
    WorkoutSessionDraft,
)
from app.services.daily_balance import daily_balance
from app.services.onboarding import getting_started_status
from app.services.overload import session_metrics


def _local_date(value: datetime, app_timezone: ZoneInfo) -> date:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.date()
    return value.astimezone(app_timezone).date()


def _latest_weigh_in(
    user_id: int,
    target_date: date,
    app_timezone: ZoneInfo,
) -> dict:
    records = db.session.execute(
        db.select(WeighIn)
        .where(WeighIn.user_id == user_id)
        .order_by(WeighIn.recorded_at.asc(), WeighIn.id.asc())
    ).scalars()
    eligible = [
        record
        for record in records
        if _local_date(record.recorded_at, app_timezone) <= target_date
    ]
    if not eligible:
        return {
            "record": None,
            "is_exact_date": False,
            "previous_record": None,
            "change_from_previous": None,
            "state": "missing",
        }
    latest = eligible[-1]
    previous = eligible[-2] if len(eligible) > 1 else None
    is_exact_date = _local_date(latest.recorded_at, app_timezone) == target_date
    return {
        "record": latest,
        "is_exact_date": is_exact_date,
        "previous_record": previous,
        "change_from_previous": (
            latest.weight_kg - previous.weight_kg if previous is not None else None
        ),
        "state": "today" if is_exact_date else "carried_forward",
    }


def _session_summaries(
    user_id: int,
    target_date: date,
    app_timezone: ZoneInfo,
) -> list[dict]:
    sessions = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == user_id)
        .options(
            selectinload(TrainingSession.exercises).selectinload(
                TrainingSessionExercise.sets
            )
        )
        .order_by(TrainingSession.performed_at.asc(), TrainingSession.id.asc())
    ).scalars()
    summaries = []
    for training_session in sessions:
        if _local_date(training_session.performed_at, app_timezone) != target_date:
            continue
        metrics = session_metrics(training_session)
        summaries.append(
            {
                "record": training_session,
                "duration_seconds": training_session.duration_seconds,
                "volume": metrics["volume"],
                "exercise_names": [
                    exercise.name for exercise in training_session.exercises
                ],
                "calories_burned": training_session.calories_burned,
            }
        )
    return summaries


def _domain_state(record, required_value) -> str:
    if record is None:
        return "missing"
    return "complete" if required_value is not None else "partial"


def _balance_state(balance) -> str:
    if balance is None:
        return "incomplete"
    if balance > 0:
        return "surplus"
    if balance < 0:
        return "deficit"
    return "even"


def _training_totals(sessions: list[dict]) -> dict:
    durations = [
        item["duration_seconds"]
        for item in sessions
        if item["duration_seconds"] is not None
    ]
    calories = [
        item["calories_burned"]
        for item in sessions
        if item["calories_burned"] is not None
    ]
    return {
        "session_count": len(sessions),
        "duration_seconds": sum(durations) if durations else None,
        "volume": sum(
            (item["volume"] for item in sessions),
            start=Decimal("0"),
        ),
        "exercise_count": sum(len(item["exercise_names"]) for item in sessions),
        "calories_burned": sum(calories) if calories else None,
    }


def _latest_medical_report(user_id: int, target_date: date):
    return db.session.execute(
        db.select(MedicalLabReport)
        .where(
            MedicalLabReport.user_id == user_id,
            MedicalLabReport.date <= target_date,
        )
        .order_by(MedicalLabReport.date.desc(), MedicalLabReport.id.desc())
    ).scalars().first()


def _activity_summary(user_id: int, target_date: date, app_timezone: ZoneInfo) -> dict:
    records = db.session.execute(
        db.select(Activity)
        .where(Activity.user_id == user_id)
        .order_by(Activity.started_at.desc(), Activity.id.desc())
    ).scalars().all()
    latest = None
    weekly = []
    for activity in records:
        activity_date = _local_date(activity.started_at, app_timezone)
        if activity_date <= target_date and latest is None:
            latest = activity
        if 0 <= (target_date - activity_date).days <= 6:
            weekly.append(activity)
    return {
        "latest": latest,
        "weekly_count": len(weekly),
        "weekly_distance_meters": sum(
            (activity.distance_meters for activity in weekly if activity.distance_meters is not None),
            start=Decimal("0"),
        ),
        "weekly_duration_seconds": sum(
            activity.duration_seconds for activity in weekly if activity.duration_seconds is not None
        ) or None,
    }


def _completion_summary(balance: dict, weight: dict, sessions: list[dict]) -> dict:
    nutrition_state = _domain_state(
        balance["nutrition"],
        balance["calories_consumed"],
    )
    energy_state = _domain_state(
        balance["energy"],
        balance["calories_expended"],
    )
    core_states = (nutrition_state, energy_state)
    completed_count = sum(state == "complete" for state in core_states)
    if completed_count == 2:
        status = "complete"
    elif all(state == "missing" for state in core_states):
        status = "empty"
    else:
        status = "partial"
    return {
        "status": status,
        "completed_count": completed_count,
        "required_count": 2,
        "nutrition_state": nutrition_state,
        "energy_state": energy_state,
        "weight_state": weight["state"],
        "training_state": "recorded" if sessions else "none",
    }


def _planned_summary(user_id: int, target_date: date) -> dict:
    records = db.session.execute(
        db.select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.deleted_at.is_(None),
            PlannedWorkout.scheduled_for_date.between(
                target_date, target_date + timedelta(days=6)
            ),
        )
        .options(
            selectinload(PlannedWorkout.training_plan),
            selectinload(PlannedWorkout.completed_session),
        )
        .order_by(PlannedWorkout.scheduled_for_date, PlannedWorkout.id)
    ).scalars().all()
    return {
        "today": [item for item in records if item.scheduled_for_date == target_date],
        "upcoming": [item for item in records if item.scheduled_for_date > target_date],
    }


def _latest_draft(user_id: int) -> WorkoutSessionDraft | None:
    return db.session.execute(
        db.select(WorkoutSessionDraft)
        .where(
            WorkoutSessionDraft.user_id == user_id,
            WorkoutSessionDraft.expires_at > datetime.now(timezone.utc),
        )
        .options(
            selectinload(WorkoutSessionDraft.training_plan),
            selectinload(WorkoutSessionDraft.training_plan_version),
            selectinload(WorkoutSessionDraft.planned_workout),
        )
        .order_by(WorkoutSessionDraft.updated_at.desc(), WorkoutSessionDraft.id.desc())
    ).scalars().first()


def _recent_session(user_id: int) -> dict | None:
    record = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == user_id)
        .options(
            selectinload(TrainingSession.training_plan),
            selectinload(TrainingSession.exercises).selectinload(
                TrainingSessionExercise.sets
            ),
        )
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
    ).scalars().first()
    if record is None:
        return None
    metrics = session_metrics(record)
    return {
        "record": record,
        "volume": metrics["volume"],
        "exercise_names": [exercise.name for exercise in record.exercises],
    }


def _attention_items(operations: dict, draft: WorkoutSessionDraft | None) -> list[dict]:
    items = []
    latest_import = operations["latest_import"]
    if latest_import is not None and latest_import.status in {"failed", "blocked"}:
        items.append(
            {
                "label": "Una importación necesita revisión.",
                "endpoint": "main.import_history_detail",
                "params": {"run_id": latest_import.id},
            }
        )
    if operations["latest_backup"] is None:
        items.append(
            {
                "label": "Todavía no has creado un backup completo.",
                "endpoint": "main.new_account_backup",
                "params": {},
            }
        )
    if operations["revoked_devices"]:
        items.append(
            {
                "label": "Hay dispositivos revocados en tu cuenta; revisa si siguen siendo necesarios.",
                "endpoint": "main.account_devices",
                "params": {},
            }
        )
    if draft is not None:
        updated_at = draft.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - updated_at > timedelta(days=1):
            items.append(
                {
                    "label": "Tienes un borrador de entrenamiento de hace más de un día.",
                    "endpoint": "sessions.new_session",
                    "params": {"planned_workout_id": draft.planned_workout.public_id}
                    if draft.planned_workout is not None
                    else {},
                }
            )
    return items


def _operation_summary(user_id: int) -> dict:
    latest_import = db.session.execute(
        db.select(ImportRun)
        .where(ImportRun.user_id == user_id)
        .order_by(ImportRun.created_at.desc(), ImportRun.id.desc())
    ).scalars().first()
    latest_export = db.session.execute(
        db.select(ExportRecord)
        .where(
            ExportRecord.user_id == user_id,
            ExportRecord.domain != "account_backup",
        )
        .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
    ).scalars().first()
    latest_backup = db.session.execute(
        db.select(ExportRecord)
        .where(
            ExportRecord.user_id == user_id,
            ExportRecord.domain == "account_backup",
        )
        .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
    ).scalars().first()
    active_devices = db.session.execute(
        db.select(func.count(ApiDevice.id)).where(
            ApiDevice.user_id == user_id,
            ApiDevice.revoked_at.is_(None),
        )
    ).scalar_one()
    revoked_devices = db.session.execute(
        db.select(func.count(ApiDevice.id)).where(
            ApiDevice.user_id == user_id,
            ApiDevice.revoked_at.is_not(None),
        )
    ).scalar_one()
    return {
        "latest_import": latest_import,
        "latest_export": latest_export,
        "latest_backup": latest_backup,
        "active_devices": active_devices,
        "revoked_devices": revoked_devices,
    }


def daily_health_dashboard(
    user_id: int,
    target_date: date,
    timezone_name: str,
) -> dict:
    app_timezone = ZoneInfo(timezone_name)
    balance = daily_balance(user_id, target_date)
    weight = _latest_weigh_in(
        user_id,
        target_date,
        app_timezone,
    )
    sessions = _session_summaries(user_id, target_date, app_timezone)
    medical_report = _latest_medical_report(user_id, target_date)
    activity_summary = _activity_summary(user_id, target_date, app_timezone)
    operations = _operation_summary(user_id)
    planned = _planned_summary(user_id, target_date)
    draft = _latest_draft(user_id)
    return {
        **balance,
        "balance_state": _balance_state(balance["balance"]),
        "weigh_in": weight["record"],
        "weigh_in_is_exact_date": weight["is_exact_date"],
        "weight_change": weight["change_from_previous"],
        "sessions": sessions,
        "training_totals": _training_totals(sessions),
        "latest_medical_report": medical_report,
        "activity_summary": activity_summary,
        "medical_marker_count": (
            len(medical_report.results) if medical_report is not None else 0
        ),
        "completion": _completion_summary(balance, weight, sessions),
        "onboarding": getting_started_status(user_id),
        "operations": operations,
        "planned": planned,
        "latest_draft": draft,
        "recent_session": _recent_session(user_id),
        "attention": _attention_items(operations, draft),
    }
