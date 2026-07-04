"""Tests for integrating FoodProduct into DailyNutrition — Phase 4."""

from decimal import Decimal
from datetime import date

from app.extensions import db
from app.models import FoodProduct, DailyNutrition, NutritionMeal, NutritionItem


def test_manual_nutrition_includes_food_product(app, client, user):
    from tests.conftest import login
    login(client)

    with app.app_context():
        product = FoodProduct(
            user_id=user,
            name="Test Apple",
            calories_per_100g=Decimal("52"),
            source="manual",
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    response = client.post(
        "/manual/nutrition",
        data={
            "date": "2026-07-05",
            "meal_type": "snack",
            "meal_name": "Afternoon Snack",
            "item_name": "Apple slices",
            "food_product_id": str(product_id),
            "grams_from_product": "150",
            "quantity": "150",
            "unit": "g",
            "calories": "78",  # 52 * 1.5
        },
        follow_redirects=True,
    )
    
    if b"Nutrici\xc3\xb3n diaria guardada correctamente." not in response.data:
        print(response.data.decode("utf-8"))
    assert response.status_code == 200
    assert b"Nutrici\xc3\xb3n diaria guardada correctamente." in response.data

    with app.app_context():
        record = db.session.execute(
            db.select(DailyNutrition).where(DailyNutrition.date == date(2026, 7, 5))
        ).scalar_one()
        assert len(record.meals) == 1
        meal = record.meals[0]
        assert meal.meal_type == "snack"
        assert len(meal.items) == 1
        item = meal.items[0]
        assert item.name == "Apple slices"
        assert item.food_product_id == product_id
        assert item.calories == Decimal("78")
