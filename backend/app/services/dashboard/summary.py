from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.dashboard.activity import ActivityTrendService
from app.services.dashboard.comparison import DashboardComparisonService
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.goals import DashboardGoalsService, goal_for_day
from app.services.dashboard.insights import DashboardInsightsService
from app.services.dashboard.nutrition import NutritionTrendService
from app.services.dashboard.serializers import serialize_dashboard
from app.services.dashboard.training import TrainingTrendService
from app.services.dashboard.weight import WeightTrendService


TWO_PLACES = Decimal("0.01")


class DashboardSummaryService:
    """Build a bounded owner-only longitudinal read model without Flask state."""

    def __init__(self):
        self.nutrition = NutritionTrendService()
        self.activity = ActivityTrendService()
        self.weight = WeightTrendService()
        self.training = TrainingTrendService()
        self.goals = DashboardGoalsService()
        self.comparison = DashboardComparisonService()
        self.insights = DashboardInsightsService()

    @staticmethod
    def _combined_range(date_range: DashboardDateRange) -> DashboardDateRange:
        return DashboardDateRange(
            preset="custom",
            start_date=date_range.previous_start,
            end_date=date_range.end_date,
            timezone=date_range.timezone,
        )

    @staticmethod
    def _goal_progress(goals: list[dict], period: dict, date_range: DashboardDateRange,
                       loaded_goals: list, loaded_training: dict, loaded_weight: list) -> list[dict]:
        nutrition = period["summary"]["nutrition"]["averages"]
        training = period["summary"]["training"]
        actuals = {
            "scheduled_workouts_completion": (training["completed_plans"], "workout"),
            "active_plan_tracking": (1 if training["planned"] else 0, "plan"),
        }
        enriched = []
        for goal in goals:
            actual, actual_unit = actuals.get(goal["type"], (None, goal["unit"]))
            days_with_data = None
            target = goal["target"]
            eligible = {}
            for offset in range(date_range.days):
                day = date_range.start_date + timedelta(days=offset)
                selected = goal_for_day(loaded_goals, goal["type"], day)
                if selected is not None:
                    eligible[day] = selected
            metric = {"nutrition_calories": "calories", "nutrition_protein": "protein",
                      "nutrition_carbohydrates": "total_carbs", "nutrition_fat": "fat"}.get(goal["type"])
            complete = True
            if metric:
                item = nutrition[metric]
                actual = item["goal_actual_average"]
                days_with_data = item["goal_data_days"]
                complete = days_with_data == item["goal_days"]
            elif goal["type"] == "daily_steps":
                points = [p for p in period["trends"]["activity"] if p["date"] in eligible and p["steps"] is not None]
                days_with_data = len(points)
                actual = (sum(Decimal(p["steps"]) for p in points) / len(points)) if points else None
                complete = days_with_data == len(eligible)
            elif goal["type"] in {"training_sessions_per_week", "active_days_per_week", "weight_logging_frequency"}:
                zone = ZoneInfo(date_range.timezone)
                def local_day(value):
                    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(zone).date()
                if goal["type"] == "weight_logging_frequency":
                    dates = {local_day(row.recorded_at) for row in loaded_weight} & eligible.keys()
                    count = len(dates)
                else:
                    dates = {row.public_id: local_day(row.performed_at) for row in loaded_training["sessions"]}
                    dates = [day for day in dates.values() if day in eligible]
                    count = len(set(dates)) if goal["type"] == "active_days_per_week" else len(dates)
                days_with_data = len(set(dates))
                # Frequency is proportional to the days where a goal actually applies.
                weekly = goal["period"] == "weekly"
                scale = Decimal(7 if weekly else 1)
                actual = Decimal(count) * scale / len(eligible) if eligible else None
                expected_daily = sum((g.target_value / (7 if g.period == "weekly" else 1)
                                      for g in eligible.values()), Decimal(0))
                target = expected_daily * scale / len(eligible) if eligible else target
            percent = None
            if complete and actual is not None and Decimal(target) > 0:
                percent = (
                    Decimal(actual) / Decimal(target) * Decimal("100")
                ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            if metric:
                percent = nutrition[metric]["percent_of_goal"]
            if actual is not None:
                actual = Decimal(actual).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            enriched.append(
                {
                    **goal,
                    "target": Decimal(target).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                    "actual": actual,
                    "data_days": days_with_data,
                    "actual_unit": actual_unit,
                    "percent": percent,
                }
            )
        return enriched

    def _period(
        self,
        date_range: DashboardDateRange,
        unit: str,
        loaded_nutrition: dict,
        loaded_weight: list,
        loaded_training: dict,
        loaded_goals: list,
    ) -> dict:
        nutrition = self.nutrition.build_from_rows(
            loaded_nutrition, loaded_goals, date_range
        )
        activity = self.activity.build_from_energy(
            loaded_nutrition["energy"], loaded_goals, date_range
        )
        weight = self.weight.build_from_rows(loaded_weight, date_range, unit)
        training = self.training.build_from_rows(loaded_training, date_range, unit)
        result = {
            "nutrient_details": nutrition.get("nutrient_details", {}),
            "summary": {
                **nutrition["summary"],
                "activity": activity["summary"],
                "weight": weight["summary"],
                "body": weight["body"],
                "training": training["summary"],
            },
            "trends": {
                **nutrition["trends"],
                "activity": activity["trend"],
                "weight": weight["trend"],
                "body": weight["body"]["metrics"],
                "training": training["trend"],
            },
            "coverage": {
                "period_days": date_range.days,
                **nutrition["coverage"],
                **activity["coverage"],
                **weight["coverage"],
                **training["coverage"],
            },
        }
        configured_goals = self.goals.build(loaded_goals, date_range)
        result["goals"] = self._goal_progress(configured_goals, result, date_range,
                                             loaded_goals, loaded_training, loaded_weight)
        return result

    def build(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        preferred_unit: str,
    ) -> dict:
        unit = preferred_unit if preferred_unit in {"kg", "lb"} else "kg"
        combined_range = self._combined_range(date_range)
        loaded_nutrition = self.nutrition.load(user_id, combined_range)
        loaded_weight = self.weight.load(user_id, combined_range)
        loaded_training = self.training.load(user_id, combined_range)
        loaded_goals = self.goals.load(user_id, combined_range)

        current = self._period(
            date_range,
            unit,
            loaded_nutrition,
            loaded_weight,
            loaded_training,
            loaded_goals,
        )
        previous_range = date_range.previous_period()
        previous = self._period(
            previous_range,
            unit,
            loaded_nutrition,
            loaded_weight,
            loaded_training,
            loaded_goals,
        )
        comparison = self.comparison.build(
            current,
            previous,
            previous_range.as_dict(),
        )
        result = {
            "range": date_range.as_dict(),
            **current,
            "previous_period": {
                "range": previous_range.as_dict(),
                "summary": previous["summary"],
                "coverage": previous["coverage"],
                "nutrient_details": previous["nutrient_details"],
            },
            "comparison": comparison,
            "insights": self.insights.build(current, previous, date_range.days),
        }
        return serialize_dashboard(result)
