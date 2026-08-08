from __future__ import annotations

from app.services.dashboard.comparison import DashboardComparisonService
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.nutrition import NutritionTrendService
from app.services.dashboard.serializers import serialize_dashboard
from app.services.dashboard.training import TrainingTrendService
from app.services.dashboard.weight import WeightTrendService


class DashboardSummaryService:
    """Coordinate bounded owner-only dashboard read models without Flask state."""

    def __init__(self):
        self.nutrition = NutritionTrendService()
        self.weight = WeightTrendService()
        self.training = TrainingTrendService()
        self.comparison = DashboardComparisonService()

    def _period(self, user_id: int, date_range: DashboardDateRange, unit: str) -> dict:
        nutrition = self.nutrition.build(user_id, date_range)
        weight = self.weight.build(user_id, date_range, unit)
        training = self.training.build(user_id, date_range, unit)
        return {
            "summary": {
                **nutrition["summary"],
                "weight": weight["summary"],
                "training": training["summary"],
            },
            "trends": {
                **nutrition["trends"],
                "weight": weight["trend"],
                "training": training["trend"],
            },
            "coverage": {
                "period_days": date_range.days,
                **nutrition["coverage"],
                **weight["coverage"],
                **training["coverage"],
            },
        }

    def build(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        preferred_unit: str,
    ) -> dict:
        unit = preferred_unit if preferred_unit in {"kg", "lb"} else "kg"
        current = self._period(user_id, date_range, unit)
        result = {
            "range": date_range.as_dict(),
            **current,
            "comparison": {},
        }
        if date_range.compare_previous:
            previous_range = date_range.previous_period()
            previous = self._period(user_id, previous_range, unit)
            result["comparison"] = self.comparison.build(
                current,
                previous,
                previous_range.as_dict(),
            )
        return serialize_dashboard(result)
