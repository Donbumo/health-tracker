from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy.orm import joinedload, selectinload, with_loader_criteria

from app.extensions import db
from app.models import (
    Activity,
    PlannedWorkout,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
)
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.provenance import source_label, source_labels


LB_PER_KG = Decimal("2.2046226218487757")
TWO_PLACES = Decimal("0.01")
WEIGHT_VOLUME_MODES = {
    "direct_total",
    "per_side",
    "bar_plus_per_side",
    "machine_initial_total",
    "machine_initial_per_side",
    "machine_external_per_side_initial_total",
    "selector_stack",
    "dumbbell_each",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_mode(training_set) -> str:
    details = training_set.load_details_json or {}
    return details.get("load_mode") or "direct_total"


def _volume(sets, unit: str) -> tuple[Decimal | None, bool]:
    if not sets:
        return None, False
    if any(_load_mode(item) not in WEIGHT_VOLUME_MODES for item in sets):
        return None, False
    total = sum(
        (item.weight_kg * Decimal(item.reps) for item in sets), Decimal("0")
    )
    if unit == "lb":
        total *= LB_PER_KG
    return total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP), True


def _percentage(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (
        Decimal(numerator) * Decimal("100") / Decimal(denominator)
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _minutes(seconds: int | None) -> Decimal | None:
    if seconds is None:
        return None
    return (Decimal(seconds) / Decimal("60")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


class TrainingTrendService:
    def load(self, user_id: int, date_range: DashboardDateRange) -> dict:
        start_at, end_at = date_range.utc_bounds()
        sessions = db.session.execute(
            db.select(TrainingSession)
            .where(
                TrainingSession.user_id == user_id,
                TrainingSession.deleted_at.is_(None),
                TrainingSession.performed_at >= start_at,
                TrainingSession.performed_at < end_at,
            )
            .options(
                joinedload(TrainingSession.training_plan),
                selectinload(TrainingSession.exercises).selectinload(
                    TrainingSessionExercise.sets
                ),
                with_loader_criteria(
                    TrainingSessionExercise,
                    TrainingSessionExercise.user_id == user_id,
                ),
                with_loader_criteria(TrainingSet, TrainingSet.user_id == user_id),
            )
            .order_by(TrainingSession.performed_at, TrainingSession.id)
        ).scalars().all()
        planned = db.session.execute(
            db.select(PlannedWorkout)
            .where(
                PlannedWorkout.user_id == user_id,
                PlannedWorkout.deleted_at.is_(None),
                PlannedWorkout.status != "cancelled",
                PlannedWorkout.scheduled_for_date.between(
                    date_range.start_date, date_range.end_date
                ),
            )
            .order_by(PlannedWorkout.scheduled_for_date, PlannedWorkout.id)
        ).scalars().all()
        completed_plan_ids = set(
            db.session.execute(
                db.select(TrainingSession.planned_workout_id)
                .join(
                    PlannedWorkout,
                    PlannedWorkout.id == TrainingSession.planned_workout_id,
                )
                .where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.deleted_at.is_(None),
                    PlannedWorkout.user_id == user_id,
                    PlannedWorkout.deleted_at.is_(None),
                    PlannedWorkout.scheduled_for_date.between(
                        date_range.start_date, date_range.end_date
                    ),
                )
            ).scalars()
        )
        activities = db.session.execute(
            db.select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.archived_at.is_(None),
                Activity.started_at >= start_at,
                Activity.started_at < end_at,
            )
            .order_by(Activity.started_at, Activity.id)
        ).scalars().all()
        return {
            "sessions": sessions,
            "planned": planned,
            "completed_plan_ids": completed_plan_ids,
            "activities": activities,
        }

    def build_from_rows(
        self,
        loaded: dict,
        date_range: DashboardDateRange,
        unit: str,
    ) -> dict:
        start_at, end_at = date_range.utc_bounds()
        sessions = [
            row
            for row in loaded["sessions"]
            if start_at <= _as_utc(row.performed_at) < end_at
        ]
        planned = [
            row
            for row in loaded["planned"]
            if date_range.start_date <= row.scheduled_for_date <= date_range.end_date
        ]
        activities = [
            row
            for row in loaded["activities"]
            if start_at <= _as_utc(row.started_at) < end_at
        ]
        completed_plan_ids = loaded["completed_plan_ids"]
        zone = ZoneInfo(date_range.timezone)
        session_days = {
            row.id: _as_utc(row.performed_at).astimezone(zone).date()
            for row in sessions
        }
        activity_days = {
            row.id: _as_utc(row.started_at).astimezone(zone).date()
            for row in activities
        }
        completed_plans = sum(
            row.status == "completed" or row.id in completed_plan_ids
            for row in planned
        )
        durations = [
            row.duration_seconds
            for row in sessions
            if row.duration_seconds is not None
        ] + [
            row.duration_seconds
            for row in activities
            if row.duration_seconds is not None
        ]
        calories = [
            row.calories_burned
            for row in sessions
            if row.calories_burned is not None
        ] + [
            row.calories_kcal
            for row in activities
            if row.calories_kcal is not None
        ]
        all_sets = [
            item
            for row in sessions
            for exercise in row.exercises
            for item in exercise.sets
        ]
        total_volume, volume_supported = _volume(all_sets, unit)

        bucket_days = 1 if date_range.days <= 31 else 7
        bucket_count = (date_range.days + bucket_days - 1) // bucket_days
        trend = []
        for index in range(bucket_count):
            bucket_start = date_range.start_date + timedelta(days=index * bucket_days)
            bucket_end = min(
                bucket_start + timedelta(days=bucket_days - 1), date_range.end_date
            )
            bucket_sessions = [
                row
                for row in sessions
                if bucket_start <= session_days[row.id] <= bucket_end
            ]
            bucket_activities = [
                row
                for row in activities
                if bucket_start <= activity_days[row.id] <= bucket_end
            ]
            bucket_plans = [
                row
                for row in planned
                if bucket_start <= row.scheduled_for_date <= bucket_end
            ]
            bucket_completed = sum(
                row.status == "completed" or row.id in completed_plan_ids
                for row in bucket_plans
            )
            bucket_durations = [
                row.duration_seconds
                for row in bucket_sessions
                if row.duration_seconds is not None
            ] + [
                row.duration_seconds
                for row in bucket_activities
                if row.duration_seconds is not None
            ]
            bucket_calories = [
                row.calories_burned
                for row in bucket_sessions
                if row.calories_burned is not None
            ] + [
                row.calories_kcal
                for row in bucket_activities
                if row.calories_kcal is not None
            ]
            bucket_sets = [
                item
                for row in bucket_sessions
                for exercise in row.exercises
                for item in exercise.sets
            ]
            bucket_volume, _ = _volume(bucket_sets, unit)
            trend.append(
                {
                    "date": bucket_start,
                    "to": bucket_end,
                    "label": (
                        bucket_start.isoformat()
                        if bucket_days == 1
                        else f"{bucket_start.isoformat()} – {bucket_end.isoformat()}"
                    ),
                    "sessions": len(bucket_sessions) + len(bucket_activities),
                    "strength_sessions": len(bucket_sessions),
                    "activity_sessions": len(bucket_activities),
                    "planned": len(bucket_plans),
                    "duration_minutes": _minutes(
                        sum(bucket_durations) if bucket_durations else None
                    ),
                    "calories": (
                        sum(bucket_calories, Decimal("0"))
                        if bucket_calories
                        else None
                    ),
                    "adherence_percent": _percentage(
                        bucket_completed, len(bucket_plans)
                    ),
                    "volume": bucket_volume,
                }
            )

        distribution = defaultdict(lambda: {"sessions": 0, "duration_seconds": 0})
        for row in sessions:
            label = row.training_plan.name if row.training_plan else "Fuerza"
            distribution[label]["sessions"] += 1
            distribution[label]["duration_seconds"] += row.duration_seconds or 0
        for row in activities:
            label = (row.activity_type or row.discipline or "Actividad").replace("_", " ").title()
            distribution[label]["sessions"] += 1
            distribution[label]["duration_seconds"] += row.duration_seconds or 0
        distribution_rows = [
            {
                "label": label,
                "sessions": value["sessions"],
                "duration_minutes": _minutes(value["duration_seconds"]),
            }
            for label, value in sorted(
                distribution.items(), key=lambda item: (-item[1]["sessions"], item[0])
            )
        ]

        duration_total = sum(durations) if durations else None
        total_sessions = len(sessions) + len(activities)
        training_sources = [
            "Importación"
            if row.source_file_id
            else "Dispositivo"
            if row.source_device_id
            else "Manual"
            for row in sessions
        ] + [
            source_label(row.source_type, has_source_file=bool(row.source_file_id))
            for row in activities
        ]
        active_dates = set(session_days.values()) | set(activity_days.values())
        return {
            "summary": {
                "sessions": total_sessions,
                "strength_sessions": len(sessions),
                "activities": len(activities),
                "planned": len(planned),
                "completed_plans": completed_plans,
                "adherence_percent": _percentage(completed_plans, len(planned)),
                "duration_seconds": duration_total,
                "duration_minutes": _minutes(duration_total),
                "duration_average_seconds": (
                    Decimal(duration_total) / Decimal(len(durations))
                    if duration_total is not None
                    else None
                ),
                "duration_sessions": len(durations),
                "calories": sum(calories, Decimal("0")) if calories else None,
                "calorie_sessions": len(calories),
                "volume": total_volume if volume_supported else None,
                "volume_unit": f"{unit}·reps",
                "volume_supported": volume_supported,
                "volume_reason": (
                    None
                    if volume_supported
                    else (
                        "Hay cargas no comparables en el periodo."
                        if all_sets
                        else "No hay series comparables en el periodo."
                    )
                ),
                "active_days": len(active_dates),
                "bucket": "day" if bucket_days == 1 else "week",
                "distribution": distribution_rows,
                "sources": source_labels(training_sources),
            },
            "trend": trend,
            "coverage": {
                "training_sessions": total_sessions,
                "strength_sessions": len(sessions),
                "imported_activities": len(activities),
                "planned_workouts": len(planned),
                "training_duration_sessions": len(durations),
            },
        }

    def build(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        unit: str,
    ) -> dict:
        return self.build_from_rows(self.load(user_id, date_range), date_range, unit)
