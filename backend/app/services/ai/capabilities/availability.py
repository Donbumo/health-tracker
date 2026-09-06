from __future__ import annotations

from sqlalchemy import or_

from app.extensions import db
from app.models.activity import Activity
from app.models.daily_energy import DailyEnergy
from app.models.engagement import UserGoal
from app.models.nutrition import DailyNutrition
from app.models.training_session import TrainingSession
from app.models.weigh_in import WeighIn
from app.services.ai.capabilities.types import DataAvailability


class AICapabilityAvailabilityService:
    """Small owner-only aggregates used by the catalog; never loads health rows."""

    def build(self, user_id: int) -> dict[str, DataAvailability]:
        goal_rows = db.session.execute(
            db.select(UserGoal.goal_type, db.func.count(UserGoal.id))
            .where(UserGoal.user_id == user_id, UserGoal.state == "active")
            .group_by(UserGoal.goal_type)
        ).all()
        goal_counts = {goal_type: int(count) for goal_type, count in goal_rows}
        counts = {
            "body": self._count(WeighIn, WeighIn.user_id == user_id),
            "nutrition": self._count(DailyNutrition, DailyNutrition.user_id == user_id),
            "training": self._count(
                TrainingSession,
                TrainingSession.user_id == user_id,
                TrainingSession.deleted_at.is_(None),
            ),
            "goals": sum(goal_counts.values()),
            "steps": self._count(
                DailyEnergy,
                DailyEnergy.user_id == user_id,
                DailyEnergy.steps.is_not(None),
            ),
            "activities": self._count(
                Activity,
                Activity.user_id == user_id,
                Activity.archived_at.is_(None),
            ),
            "energy": self._count(
                DailyEnergy,
                DailyEnergy.user_id == user_id,
                or_(
                    DailyEnergy.total_calories.is_not(None),
                    DailyEnergy.active_calories.is_not(None),
                    DailyEnergy.resting_calories.is_not(None),
                ),
            ),
        }
        counts["activity"] = counts["steps"] + counts["activities"]
        counts["energy"] += counts["nutrition"]
        counts["all"] = sum(
            counts[item]
            for item in ("body", "nutrition", "training", "activity", "energy", "goals")
        )
        counts["data"] = counts["all"]
        result = {}
        for domain in ("all", "energy", "nutrition", "body", "activity", "training", "goals", "data"):
            count = counts[domain]
            result[domain] = DataAvailability(
                domain=domain,
                record_count=count,
                status="available" if count else "no_data",
                reason=None if count else "Aún no hay datos para esta lectura.",
                metric_counts=(
                    {"steps": counts["steps"], "activity": counts["activities"]}
                    if domain == "activity"
                    else goal_counts
                    if domain == "goals"
                    else {}
                ),
            )
        return result

    @staticmethod
    def _count(model, *criteria) -> int:
        return int(
            db.session.scalar(
                db.select(db.func.count()).select_from(model).where(*criteria)
            )
            or 0
        )
