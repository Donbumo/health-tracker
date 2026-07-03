from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import TrainingSession, WeighIn
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
) -> tuple[WeighIn | None, bool]:
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
        return None, False
    latest = eligible[-1]
    return latest, _local_date(latest.recorded_at, app_timezone) == target_date


def _session_summaries(
    user_id: int,
    target_date: date,
    app_timezone: ZoneInfo,
) -> list[dict]:
    sessions = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == user_id)
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


def daily_health_dashboard(
    user_id: int,
    target_date: date,
    timezone_name: str,
) -> dict:
    app_timezone = ZoneInfo(timezone_name)
    balance = daily_balance(user_id, target_date)
    weigh_in, weigh_in_is_exact_date = _latest_weigh_in(
        user_id,
        target_date,
        app_timezone,
    )
    return {
        **balance,
        "weigh_in": weigh_in,
        "weigh_in_is_exact_date": weigh_in_is_exact_date,
        "sessions": _session_summaries(user_id, target_date, app_timezone),
    }
