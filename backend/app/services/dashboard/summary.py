from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.services.dashboard.activity import ActivityTrendService
from app.services.dashboard.comparison import DashboardComparisonService
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.goals import DashboardGoalsService
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
    def _goal_progress(goals: list[dict], period: dict, date_range: DashboardDateRange) -> list[dict]:
        nutrition = period["summary"]["nutrition"]["averages"]
        activity = period["summary"]["activity"]
        training = period["summary"]["training"]
        weight = period["summary"]["weight"]
        weeks = Decimal(date_range.days) / Decimal("7")
        actuals = {
            "nutrition_calories": (nutrition["calories"]["average"], "kcal"),
            "nutrition_protein": (nutrition["protein"]["average"], "g"),
            "nutrition_carbohydrates": (nutrition["net_carbs"]["average"], "g"),
            "nutrition_fat": (nutrition["fat"]["average"], "g"),
            "daily_steps": (activity["steps_average"], "step"),
            "training_sessions_per_week": (
                (Decimal(training["sessions"]) / weeks).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                "session",
            ),
            "active_days_per_week": (
                (Decimal(training["active_days"]) / weeks).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                "day",
            ),
            "scheduled_workouts_completion": (training["completed_plans"], "workout"),
            "weight_logging_frequency": (
                (Decimal(weight["entries"]) / weeks).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                "log",
            ),
            "active_plan_tracking": (1 if training["planned"] else 0, "plan"),
        }
        enriched = []
        for goal in goals:
            actual, actual_unit = actuals.get(goal["type"], (None, goal["unit"]))
            percent = None
            if actual is not None and Decimal(goal["target"]) > 0:
                percent = (
                    Decimal(actual) / Decimal(goal["target"]) * Decimal("100")
                ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            enriched.append(
                {
                    **goal,
                    "actual": actual,
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
        result["goals"] = self._goal_progress(configured_goals, result, date_range)
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
            },
            "comparison": comparison,
            "insights": self.insights.build(current, previous, date_range.days),
        }
        return serialize_dashboard(result)
