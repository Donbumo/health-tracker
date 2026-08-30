from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.models import DailyEnergy, UserGoal
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.goals import goal_for_day
from app.services.dashboard.nutrition import effective_energy_value
from app.services.dashboard.provenance import source_label, source_labels


TWO_PLACES = Decimal("0.01")


def _dates(date_range: DashboardDateRange):
    for offset in range(date_range.days):
        yield date_range.start_date + timedelta(days=offset)


def _average(total, count: int):
    if total is None or count <= 0:
        return None
    return (Decimal(total) / Decimal(count)).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


class ActivityTrendService:
    def build_from_energy(
        self,
        energy_rows: list[DailyEnergy],
        goals: list[UserGoal],
        date_range: DashboardDateRange,
    ) -> dict:
        by_date = defaultdict(list)
        for row in energy_rows:
            if date_range.start_date <= row.date <= date_range.end_date:
                by_date[row.date].append(row)

        points = []
        for day in _dates(date_range):
            rows = by_date.get(day, [])
            steps, steps_row = effective_energy_value(rows, "steps")
            distance, distance_row = effective_energy_value(rows, "distance_meters")
            active_calories, calories_row = effective_energy_value(
                rows, "active_calories"
            )
            goal = goal_for_day(goals, "daily_steps", day)
            labels = source_labels(
                source_label(
                    row.source if row is not None else None,
                    has_source_file=bool(row and row.source_file_id),
                )
                for row in (steps_row, distance_row, calories_row)
            )
            points.append(
                {
                    "date": day,
                    "steps": steps,
                    "step_goal": goal.target_value if goal is not None else None,
                    "distance_km": (
                        (distance / Decimal("1000")).quantize(
                            TWO_PLACES, rounding=ROUND_HALF_UP
                        )
                        if distance is not None
                        else None
                    ),
                    "active_calories": active_calories,
                    "sources": labels,
                }
            )

        step_values = [point["steps"] for point in points if point["steps"] is not None]
        distance_values = [
            point["distance_km"]
            for point in points
            if point["distance_km"] is not None
        ]
        calorie_values = [
            point["active_calories"]
            for point in points
            if point["active_calories"] is not None
        ]
        goal_points = [point for point in points if point["step_goal"] is not None]
        paired_goal_points = [
            point for point in goal_points if point["steps"] is not None
        ]
        steps_total = sum(step_values) if step_values else None
        distance_total = (
            sum(distance_values, Decimal("0")) if distance_values else None
        )
        active_calories_total = (
            sum(calorie_values, Decimal("0")) if calorie_values else None
        )
        activity_days = sum(
            any(point[key] is not None for key in ("steps", "distance_km", "active_calories"))
            for point in points
        )
        return {
            "summary": {
                "steps_total": steps_total,
                "steps_average": _average(steps_total, len(step_values)),
                "distance_km": distance_total,
                "active_calories": active_calories_total,
                "days_at_goal": sum(
                    point["steps"] >= point["step_goal"]
                    for point in paired_goal_points
                ),
                "goal_days": len(goal_points),
                "paired_goal_days": len(paired_goal_points),
                "step_days": len(step_values),
                "distance_days": len(distance_values),
                "active_calorie_days": len(calorie_values),
                "sources": source_labels(
                    source for point in points for source in point["sources"]
                ),
            },
            "trend": points,
            "coverage": {
                "activity_days": activity_days,
                "steps_days": len(step_values),
                "distance_days": len(distance_values),
                "active_calorie_days": len(calorie_values),
            },
        }
