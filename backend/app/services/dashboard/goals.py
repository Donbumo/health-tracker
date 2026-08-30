from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_

from app.extensions import db
from app.models import UserGoal
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.provenance import source_label


GOAL_PRESENTATION = {
    "nutrition_calories": ("Calorías", "Nutrición"),
    "nutrition_protein": ("Proteína", "Nutrición"),
    "nutrition_carbohydrates": ("Carbohidratos", "Nutrición"),
    "nutrition_fat": ("Grasa", "Nutrición"),
    "daily_steps": ("Pasos", "Actividad"),
    "training_sessions_per_week": ("Sesiones", "Entrenamiento"),
    "active_days_per_week": ("Días activos", "Entrenamiento"),
    "scheduled_workouts_completion": ("Entrenamientos planeados", "Entrenamiento"),
    "weight_logging_frequency": ("Registro de peso", "Peso"),
    "active_plan_tracking": ("Plan activo", "Entrenamiento"),
}

UNIT_LABELS = {
    "day": "días",
    "log": "registros",
    "session": "sesiones",
    "step": "pasos",
    "workout": "entrenamientos",
}


def _dates(date_range: DashboardDateRange):
    for offset in range(date_range.days):
        yield date_range.start_date + timedelta(days=offset)


def goal_for_day(goals: list[UserGoal], goal_type: str, day) -> UserGoal | None:
    for goal in goals:
        if goal.goal_type != goal_type:
            continue
        if goal.start_date > day or (goal.end_date and goal.end_date < day):
            continue
        applicable_days = set(goal.applicable_days_json or range(1, 8))
        if goal.period != "selected_days" or day.isoweekday() in applicable_days:
            return goal
    return None


class DashboardGoalsService:
    def load(self, user_id: int, date_range: DashboardDateRange) -> list[UserGoal]:
        return db.session.execute(
            db.select(UserGoal)
            .where(
                UserGoal.user_id == user_id,
                UserGoal.state == "active",
                UserGoal.start_date <= date_range.end_date,
                or_(
                    UserGoal.end_date.is_(None),
                    UserGoal.end_date >= date_range.start_date,
                ),
            )
            .order_by(UserGoal.updated_at.desc(), UserGoal.id.desc())
        ).scalars().all()

    def build(self, goals: list[UserGoal], date_range: DashboardDateRange) -> list[dict]:
        result = []
        for goal_type, (label, domain) in GOAL_PRESENTATION.items():
            applicable = [
                goal_for_day(goals, goal_type, day) for day in _dates(date_range)
            ]
            applicable = [goal for goal in applicable if goal is not None]
            if not applicable:
                continue
            selected = applicable[-1]
            daily_values = [goal.target_value for goal in applicable]
            target = selected.target_value
            if selected.period in {"daily", "selected_days"}:
                target = (
                    sum(daily_values, Decimal("0")) / Decimal(len(daily_values))
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result.append(
                {
                    "type": goal_type,
                    "label": label,
                    "domain": domain,
                    "target": target,
                    "unit": selected.unit,
                    "display_unit": UNIT_LABELS.get(selected.unit, selected.unit),
                    "period": selected.period,
                    "applicable_days": len(applicable),
                    "source": source_label(selected.source),
                }
            )
        return result
