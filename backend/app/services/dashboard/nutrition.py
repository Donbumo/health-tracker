from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, UserGoal
from app.services.dashboard.date_range import DashboardDateRange


TWO_PLACES = Decimal("0.01")


def _sum_or_none(values) -> Decimal | None:
    available = [value for value in values if value is not None]
    return sum(available, Decimal("0")) if available else None


def _average(total: Decimal | None, count: int) -> Decimal | None:
    if total is None or count <= 0:
        return None
    return (total / Decimal(count)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _percentage(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    return ((numerator / denominator) * Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def _dates(date_range: DashboardDateRange):
    for offset in range(date_range.days):
        yield date_range.start_date + timedelta(days=offset)


def _effective_energy(rows: list[DailyEnergy]) -> dict:
    effective = {}
    for row in rows:
        if row.total_calories is None:
            continue
        current = effective.get(row.date)
        if current is None or (row.source == "manual" and current.source != "manual"):
            effective[row.date] = row
    return effective


def _goal_for_day(goals: list[UserGoal], day):
    for goal in goals:
        if goal.unit != "g" or goal.period not in {"daily", "selected_days"}:
            continue
        if goal.start_date > day or (goal.end_date and goal.end_date < day):
            continue
        applicable_days = set(goal.applicable_days_json or range(1, 8))
        if day.isoweekday() in applicable_days:
            return goal
    return None


class NutritionTrendService:
    def build(self, user_id: int, date_range: DashboardDateRange) -> dict:
        nutrition_rows = db.session.execute(
            db.select(DailyNutrition)
            .where(
                DailyNutrition.user_id == user_id,
                DailyNutrition.date.between(
                    date_range.start_date, date_range.end_date
                ),
            )
            .order_by(DailyNutrition.date)
        ).scalars().all()
        energy_rows = db.session.execute(
            db.select(DailyEnergy)
            .where(
                DailyEnergy.user_id == user_id,
                DailyEnergy.date.between(date_range.start_date, date_range.end_date),
            )
            .order_by(
                DailyEnergy.date,
                DailyEnergy.updated_at.desc(),
                DailyEnergy.id.desc(),
            )
        ).scalars().all()
        goals = db.session.execute(
            db.select(UserGoal)
            .where(
                UserGoal.user_id == user_id,
                UserGoal.state == "active",
                UserGoal.goal_type == "nutrition_protein",
                UserGoal.start_date <= date_range.end_date,
                or_(
                    UserGoal.end_date.is_(None),
                    UserGoal.end_date >= date_range.start_date,
                ),
            )
            .order_by(UserGoal.updated_at.desc(), UserGoal.id.desc())
        ).scalars().all()

        nutrition_by_date = {row.date: row for row in nutrition_rows}
        energy_by_date = _effective_energy(energy_rows)
        energy_points = []
        protein_points = []
        for day in _dates(date_range):
            nutrition = nutrition_by_date.get(day)
            energy = energy_by_date.get(day)
            consumed = nutrition.calories if nutrition is not None else None
            expended = energy.total_calories if energy is not None else None
            balance = (
                consumed - expended
                if consumed is not None and expended is not None
                else None
            )
            goal = _goal_for_day(goals, day)
            protein_points.append(
                {
                    "date": day,
                    "grams": nutrition.protein_g if nutrition is not None else None,
                    "target": goal.target_value if goal is not None else None,
                }
            )
            energy_points.append(
                {
                    "date": day,
                    "consumed": consumed,
                    "expended": expended,
                    "balance": balance,
                    "source": energy.source if energy is not None else None,
                }
            )

        consumed_values = [point["consumed"] for point in energy_points]
        expended_values = [point["expended"] for point in energy_points]
        balance_values = [point["balance"] for point in energy_points]
        consumed_total = _sum_or_none(consumed_values)
        expended_total = _sum_or_none(expended_values)
        balance_total = _sum_or_none(balance_values)
        nutrition_days = sum(value is not None for value in consumed_values)
        energy_days = sum(value is not None for value in expended_values)
        balance_days = sum(value is not None for value in balance_values)

        protein_values = [point["grams"] for point in protein_points]
        protein_total = _sum_or_none(protein_values)
        protein_days = sum(value is not None for value in protein_values)
        goal_points = [point for point in protein_points if point["target"] is not None]
        goal_total = _sum_or_none(point["target"] for point in goal_points)
        paired = [
            point
            for point in goal_points
            if point["grams"] is not None
        ]
        paired_consumed = _sum_or_none(point["grams"] for point in paired)
        paired_goal = _sum_or_none(point["target"] for point in paired)
        protein_balance = (
            paired_consumed - paired_goal
            if paired_consumed is not None and paired_goal is not None
            else None
        )
        compliance = (
            _percentage(paired_consumed, paired_goal)
            if paired_consumed is not None and paired_goal is not None
            else None
        )

        return {
            "summary": {
                "energy": {
                    "consumed_total": consumed_total,
                    "expended_total": expended_total,
                    "balance_total": balance_total,
                    "consumed_average": _average(consumed_total, nutrition_days),
                    "expended_average": _average(expended_total, energy_days),
                    "balance_average": _average(balance_total, balance_days),
                    "nutrition_days": nutrition_days,
                    "energy_days": energy_days,
                    "balance_days": balance_days,
                },
                "protein": {
                    "total": protein_total,
                    "average": _average(protein_total, protein_days),
                    "goal_total": goal_total,
                    "goal_average": _average(goal_total, len(goal_points)),
                    "balance": protein_balance,
                    "compliance_percent": compliance,
                    "days_at_goal": sum(
                        point["grams"] >= point["target"] for point in paired
                    ),
                    "protein_days": protein_days,
                    "goal_days": len(goal_points),
                    "paired_days": len(paired),
                },
            },
            "trends": {
                "energy": energy_points,
                "protein": protein_points,
            },
            "coverage": {
                "nutrition_days": nutrition_days,
                "energy_days": energy_days,
                "balance_days": balance_days,
                "protein_days": protein_days,
                "protein_goal_days": len(goal_points),
            },
        }
