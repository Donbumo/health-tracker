from datetime import date, datetime
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
    TrainingSession,
    TrainingSessionExercise,
    User,
    WeighIn,
)
from app.services.daily_balance import daily_balance
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


def _has_record(model, user_id: int) -> bool:
    return db.session.execute(
        db.select(model.id).where(model.user_id == user_id).limit(1)
    ).scalar_one_or_none() is not None


def _onboarding_checklist(user_id: int) -> dict:
    user = db.session.get(User, user_id)
    has_weight = _has_record(WeighIn, user_id)
    has_energy = _has_record(DailyEnergy, user_id)
    has_nutrition = _has_record(DailyNutrition, user_id)
    has_any_data = has_weight or has_energy or has_nutrition
    items = [
        {
            "label": "Cuenta lista",
            "complete": user is not None and bool(user.email or user.username),
            "help": "Tu login ya está activo.",
            "url_endpoint": None,
        },
        {
            "label": "Registrar primer peso",
            "complete": has_weight,
            "help": "Sirve como referencia corporal inicial.",
            "url_endpoint": "main.manual_weigh_in",
        },
        {
            "label": "Registrar energía",
            "complete": has_energy,
            "help": "Agrega gasto, pasos o calorías del día.",
            "url_endpoint": "wellness.manual_energy",
        },
        {
            "label": "Registrar nutrición",
            "complete": has_nutrition,
            "help": "Captura al menos una comida o item.",
            "url_endpoint": "wellness.manual_nutrition",
        },
        {
            "label": "Revisar dashboard",
            "complete": has_any_data,
            "help": "Vuelve aquí para ver tu resumen diario.",
            "url_endpoint": "main.dashboard",
        },
        {
            "label": "Exportar respaldo",
            "complete": has_any_data,
            "help": "Descarga tu JSON cuando tengas datos de prueba.",
            "url_endpoint": "main.export_account_data",
        },
    ]
    return {
        "items": items,
        "completed_count": sum(1 for item in items if item["complete"]),
        "total_count": len(items),
    }


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
    return {
        "latest_import": latest_import,
        "latest_export": latest_export,
        "latest_backup": latest_backup,
        "active_devices": active_devices,
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
        "onboarding": _onboarding_checklist(user_id),
        "operations": _operation_summary(user_id),
    }
