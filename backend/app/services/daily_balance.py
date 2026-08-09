from datetime import date

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition


def effective_energy_record(user_id: int, target_date: date) -> DailyEnergy | None:
    """Choose one daily source without merging potentially overlapping devices.

    A manual correction has explicit precedence. Otherwise the most recently
    updated source wins deterministically while every source remains preserved.
    """
    records = db.session.execute(
        db.select(DailyEnergy)
        .where(DailyEnergy.user_id == user_id, DailyEnergy.date == target_date)
        .order_by(DailyEnergy.updated_at.desc(), DailyEnergy.id.desc())
    ).scalars().all()
    return next((item for item in records if item.source == "manual"), records[0] if records else None)


def daily_balance(user_id: int, target_date: date) -> dict:
    nutrition = db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.user_id == user_id,
            DailyNutrition.date == target_date,
        )
    ).scalar_one_or_none()
    energy = effective_energy_record(user_id, target_date)

    calories_consumed = nutrition.calories if nutrition is not None else None
    calories_expended = energy.total_calories if energy is not None else None
    balance = (
        calories_consumed - calories_expended
        if calories_consumed is not None and calories_expended is not None
        else None
    )
    return {
        "date": target_date,
        "nutrition": nutrition,
        "energy": energy,
        "calories_consumed": calories_consumed,
        "protein_g": nutrition.protein_g if nutrition is not None else None,
        "fat_g": nutrition.fat_g if nutrition is not None else None,
        "net_carbs_g": nutrition.net_carbs_g if nutrition is not None else None,
        "fiber_g": nutrition.fiber_g if nutrition is not None else None,
        "calories_expended": calories_expended,
        "active_calories": energy.active_calories if energy is not None else None,
        "balance": balance,
        "complete": balance is not None,
    }
