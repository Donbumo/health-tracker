from datetime import date

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition
from app.services.nutrition_intelligence import comparison_value


def effective_energy_record(user_id: int, target_date: date) -> DailyEnergy | None:
    from app.services.energy_days import view
    return view(user_id, target_date)


def daily_balance(user_id: int, target_date: date) -> dict:
    nutrition = db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.user_id == user_id,
            DailyNutrition.date == target_date,
        )
    ).scalar_one_or_none()
    energy = effective_energy_record(user_id, target_date)

    calories_consumed = nutrition.calories if nutrition is not None else None
    comparable = comparison_value(nutrition, 'calories')
    calories_expended = energy.total_calories if energy is not None else None
    balance = (
        comparable - calories_expended
        if comparable is not None and calories_expended is not None
        else None
    )
    return {
        "date": target_date,
        "nutrition": nutrition,
        "energy": energy,
        "calories_consumed": calories_consumed,
        "calories_comparable": comparable,
        "nutrient_details": nutrition.nutrition_summary_json if nutrition else None,
        "protein_g": nutrition.protein_g if nutrition is not None else None,
        "fat_g": nutrition.fat_g if nutrition is not None else None,
        "net_carbs_g": nutrition.net_carbs_g if nutrition is not None else None,
        "fiber_g": nutrition.fiber_g if nutrition is not None else None,
        "calories_expended": calories_expended,
        "active_calories": energy.active_calories if energy is not None else None,
        "balance": balance,
        "complete": balance is not None,
    }
