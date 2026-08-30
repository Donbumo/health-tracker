from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, UserGoal
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.goals import DashboardGoalsService, goal_for_day
from app.services.dashboard.provenance import source_label, source_labels


TWO_PLACES = Decimal("0.01")
NUTRITION_METRICS = (
    ("calories", "Calorías", "calories", "kcal", "nutrition_calories"),
    ("protein", "Proteína", "protein_g", "g", "nutrition_protein"),
    ("fat", "Grasa", "fat_g", "g", "nutrition_fat"),
    ("net_carbs", "Carbohidratos netos", "net_carbs_g", "g", "nutrition_carbohydrates"),
    ("fiber", "Fibra", "fiber_g", "g", None),
)


def _sum_or_none(values) -> Decimal | None:
    available = [value for value in values if value is not None]
    return sum(available, Decimal("0")) if available else None


def _average(total: Decimal | None, count: int) -> Decimal | None:
    if total is None or count <= 0:
        return None
    return (total / Decimal(count)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _percentage(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return ((numerator / denominator) * Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


def _dates(date_range: DashboardDateRange):
    for offset in range(date_range.days):
        yield date_range.start_date + timedelta(days=offset)


def effective_energy_value(rows: list[DailyEnergy], field: str):
    available = [row for row in rows if getattr(row, field) is not None]
    if not available:
        return None, None
    manual = next((row for row in available if row.source == "manual"), None)
    selected = manual or available[0]
    return getattr(selected, field), selected


def _rolling(points: list[dict], key: str, output_key: str) -> None:
    for index, point in enumerate(points):
        window = points[max(0, index - 6) : index + 1]
        values = [item[key] for item in window if item[key] is not None]
        point[output_key] = _average(_sum_or_none(values), len(values))
        point[f"{output_key}_days"] = len(values)


class NutritionTrendService:
    def load(self, user_id: int, date_range: DashboardDateRange) -> dict:
        nutrition_rows = db.session.execute(
            db.select(DailyNutrition)
            .where(
                DailyNutrition.user_id == user_id,
                DailyNutrition.date.between(date_range.start_date, date_range.end_date),
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
        return {"nutrition": nutrition_rows, "energy": energy_rows}

    def build_from_rows(
        self,
        loaded: dict,
        goals: list[UserGoal],
        date_range: DashboardDateRange,
    ) -> dict:
        nutrition_by_date = {
            row.date: row
            for row in loaded["nutrition"]
            if date_range.start_date <= row.date <= date_range.end_date
        }
        energy_by_date = defaultdict(list)
        for row in loaded["energy"]:
            if date_range.start_date <= row.date <= date_range.end_date:
                energy_by_date[row.date].append(row)

        energy_points = []
        protein_points = []
        for day in _dates(date_range):
            nutrition = nutrition_by_date.get(day)
            expended, energy = effective_energy_value(
                energy_by_date.get(day, []), "total_calories"
            )
            consumed = nutrition.calories if nutrition is not None else None
            balance = (
                consumed - expended
                if consumed is not None and expended is not None
                else None
            )
            intake_source = source_label(
                nutrition.source if nutrition is not None else None,
                has_source_file=bool(nutrition and nutrition.source_file_id),
            )
            expenditure_source = source_label(
                energy.source if energy is not None else None,
                has_source_file=bool(energy and energy.source_file_id),
            )
            energy_points.append(
                {
                    "date": day,
                    "consumed": consumed,
                    "expended": expended,
                    "balance": balance,
                    "source": energy.source if energy is not None else None,
                    "intake_source": intake_source,
                    "expenditure_source": expenditure_source,
                    "sources": source_labels((intake_source, expenditure_source)),
                }
            )
            protein_goal = goal_for_day(goals, "nutrition_protein", day)
            protein_points.append(
                {
                    "date": day,
                    "grams": nutrition.protein_g if nutrition is not None else None,
                    "target": protein_goal.target_value if protein_goal else None,
                }
            )

        _rolling(energy_points, "consumed", "consumed_rolling_7d")
        _rolling(energy_points, "expended", "expended_rolling_7d")
        consumed_values = [point["consumed"] for point in energy_points]
        expended_values = [point["expended"] for point in energy_points]
        balance_values = [point["balance"] for point in energy_points]
        consumed_total = _sum_or_none(consumed_values)
        expended_total = _sum_or_none(expended_values)
        balance_total = _sum_or_none(balance_values)
        nutrition_days = sum(value is not None for value in consumed_values)
        energy_days = sum(value is not None for value in expended_values)
        balance_days = sum(value is not None for value in balance_values)

        macro_summaries = {}
        nutrition_sources = []
        for row in nutrition_by_date.values():
            nutrition_sources.append(
                source_label(row.source, has_source_file=bool(row.source_file_id))
            )
        for key, label, field, unit, goal_type in NUTRITION_METRICS:
            values = [
                getattr(row, field)
                for row in nutrition_by_date.values()
                if getattr(row, field) is not None
            ]
            total = _sum_or_none(values)
            targets = []
            if goal_type:
                for day in _dates(date_range):
                    goal = goal_for_day(goals, goal_type, day)
                    if goal is not None:
                        targets.append(goal.target_value)
            goal_average = _average(_sum_or_none(targets), len(targets))
            average = _average(total, len(values))
            macro_summaries[key] = {
                "label": label,
                "average": average,
                "unit": unit,
                "days": len(values),
                "goal": goal_average,
                "goal_days": len(targets),
                "percent_of_goal": _percentage(average, goal_average),
            }

        protein_values = [point["grams"] for point in protein_points]
        protein_total = _sum_or_none(protein_values)
        protein_days = sum(value is not None for value in protein_values)
        goal_points = [point for point in protein_points if point["target"] is not None]
        paired = [point for point in goal_points if point["grams"] is not None]
        paired_consumed = _sum_or_none(point["grams"] for point in paired)
        paired_goal = _sum_or_none(point["target"] for point in paired)
        protein_balance = (
            paired_consumed - paired_goal
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
                    "complete_days": balance_days,
                    "incomplete_days": date_range.days - balance_days,
                    "is_partial": balance_days < date_range.days,
                    "sources": source_labels(
                        source
                        for point in energy_points
                        for source in point["sources"]
                    ),
                },
                "nutrition": {
                    "averages": macro_summaries,
                    "sources": source_labels(nutrition_sources),
                },
                "protein": {
                    "total": protein_total,
                    "average": _average(protein_total, protein_days),
                    "goal_total": _sum_or_none(point["target"] for point in goal_points),
                    "goal_average": _average(
                        _sum_or_none(point["target"] for point in goal_points),
                        len(goal_points),
                    ),
                    "balance": protein_balance,
                    "compliance_percent": _percentage(paired_consumed, paired_goal),
                    "days_at_goal": sum(
                        point["grams"] >= point["target"] for point in paired
                    ),
                    "protein_days": protein_days,
                    "goal_days": len(goal_points),
                    "paired_days": len(paired),
                },
            },
            "trends": {"energy": energy_points, "protein": protein_points},
            "coverage": {
                "nutrition_days": nutrition_days,
                "energy_days": energy_days,
                "balance_days": balance_days,
                "complete_energy_days": balance_days,
                "incomplete_energy_days": date_range.days - balance_days,
                "protein_days": protein_days,
                "protein_goal_days": len(goal_points),
            },
        }

    def build(self, user_id: int, date_range: DashboardDateRange) -> dict:
        goals = DashboardGoalsService().load(user_id, date_range)
        return self.build_from_rows(self.load(user_id, date_range), goals, date_range)
