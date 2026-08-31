from __future__ import annotations

from app.extensions import db
from app.models.nutrition import DailyNutrition, NutritionItem, NutritionMeal


class NutritionPatternsService:
    """Owner-only aggregate read model. It describes records, never clinical meaning."""

    METRICS = (
        "calories",
        "protein_g",
        "fat_g",
        "net_carbs_g",
        "total_carbs_g",
        "fiber_g",
        "sugar_g",
        "sodium_mg",
    )

    def build(self, user_id: int, date_range) -> dict:
        day_filter = (
            DailyNutrition.user_id == user_id,
            DailyNutrition.date >= date_range.start_date,
            DailyNutrition.date <= date_range.end_date,
        )
        days_with_records = int(
            db.session.scalar(
                db.select(db.func.count()).select_from(DailyNutrition).where(*day_filter)
            )
            or 0
        )
        meal_rows = db.session.execute(
            db.select(NutritionMeal.meal_type, db.func.count(NutritionMeal.id))
            .join(DailyNutrition, NutritionMeal.daily_nutrition_id == DailyNutrition.id)
            .where(*day_filter)
            .group_by(NutritionMeal.meal_type)
            .order_by(db.func.count(NutritionMeal.id).desc(), NutritionMeal.meal_type)
        ).all()
        item_rows = db.session.execute(
            db.select(NutritionItem.name, db.func.count(NutritionItem.id))
            .join(NutritionMeal, NutritionItem.nutrition_meal_id == NutritionMeal.id)
            .join(DailyNutrition, NutritionMeal.daily_nutrition_id == DailyNutrition.id)
            .where(*day_filter)
            .group_by(NutritionItem.name)
            .order_by(db.func.count(NutritionItem.id).desc(), NutritionItem.name)
            .limit(10)
        ).all()
        metric_stats = {}
        for name in self.METRICS:
            column = getattr(DailyNutrition, name)
            count, average, minimum, maximum = db.session.execute(
                db.select(
                    db.func.count(column),
                    db.func.avg(column),
                    db.func.min(column),
                    db.func.max(column),
                ).where(*day_filter)
            ).one()
            metric_stats[name] = {
                "days_with_data": int(count or 0),
                "average": average,
                "minimum": minimum,
                "maximum": maximum,
            }
        source_rows = db.session.execute(
            db.select(DailyNutrition.source, db.func.count(DailyNutrition.id))
            .where(*day_filter)
            .group_by(DailyNutrition.source)
            .order_by(db.func.count(DailyNutrition.id).desc(), DailyNutrition.source)
        ).all()
        return {
            "period": date_range.as_dict(),
            "frequency": {
                "period_days": date_range.days,
                "days_with_records": days_with_records,
                "days_without_records": max(0, date_range.days - days_with_records),
            },
            "meal_type_distribution": [
                {"meal_type": meal_type, "records": int(count)}
                for meal_type, count in meal_rows
            ],
            "recorded_hours": {
                "available": False,
                "reason": "Los registros de comida actuales no conservan una hora de comida separada.",
            },
            "repeated_items": [
                {"name": name, "records": int(count)} for name, count in item_rows
            ],
            "metric_consistency": metric_stats,
            "coverage": {
                "days_with_records": days_with_records,
                "period_days": date_range.days,
            },
            "source_counts": [
                {"source": source, "records": int(count)}
                for source, count in source_rows
            ],
        }
