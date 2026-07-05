"""Tests for using recipes as daily nutrition items."""

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, Recipe, UploadedFile, User
from app.services.importers.daily_nutrition import (
    DailyNutritionImportError,
    import_daily_nutrition_file,
)
from app.services.manual_json import build_daily_nutrition_document, generate_standard_json
from app.services.recipes import create_recipe_from_products
from app.services.validation import validate_json_document
from tests.conftest import login


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _make_product(user_id: int, name: str = "Demo Product", **kwargs) -> FoodProduct:
    defaults = {
        "brand": "Demo Brand",
        "source": "manual",
        "calories_per_100g": Decimal("300.000"),
        "protein_g_per_100g": Decimal("20.000"),
        "fat_g_per_100g": Decimal("10.000"),
        "carbs_g_per_100g": Decimal("30.000"),
        "net_carbs_g_per_100g": Decimal("20.000"),
        "fiber_g_per_100g": Decimal("10.000"),
        "sodium_mg_per_100g": Decimal("100.000"),
    }
    defaults.update(kwargs)
    product = FoodProduct(user_id=user_id, name=name, **defaults)
    db.session.add(product)
    db.session.flush()
    return product


def _make_recipe(user_id: int, name: str = "Demo Recipe") -> Recipe:
    product = _make_product(
        user_id,
        "Recipe Ingredient Product",
        calories_per_100g=Decimal("380.000"),
        protein_g_per_100g=Decimal("85.000"),
        fat_g_per_100g=Decimal("2.000"),
        carbs_g_per_100g=Decimal("0.000"),
        net_carbs_g_per_100g=Decimal("0.000"),
        fiber_g_per_100g=Decimal("0.000"),
        sodium_mg_per_100g=Decimal("100.000"),
    )
    return create_recipe_from_products(
        user_id=user_id,
        name=name,
        servings=Decimal("2.000"),
        yield_weight_g=Decimal("500.000"),
        ingredients=[
            {
                "food_product_id": product.id,
                "quantity_g": Decimal("40.000"),
            }
        ],
    )


def test_manual_nutrition_includes_recipe_reference(app, client, user):
    login(client)

    with app.app_context():
        recipe = _make_recipe(user, "Licuado receta")
        db.session.commit()
        recipe_id = recipe.id

    response = client.post(
        "/manual/nutrition",
        data={
            "date": "2026-07-08",
            "meal_type": "snack",
            "meal_name": "Snack con receta",
            "item_name": "Licuado receta",
            "food_product_id": "0",
            "grams_from_product": "",
            "recipe_id": str(recipe_id),
            "recipe_amount": "1",
            "recipe_unit": "serving",
            "quantity": "1",
            "unit": "serving",
            "calories": "76",
            "protein_g": "17",
            "fat_g": "0.4",
            "net_carbs_g": "0",
            "total_carbs_g": "0",
            "fiber_g": "0",
            "sugar_g": "0",
            "sodium_mg": "20",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Nutrici" in response.data

    with app.app_context():
        record = db.session.execute(
            db.select(DailyNutrition).where(DailyNutrition.date == date(2026, 7, 8))
        ).scalar_one()
        item = record.meals[0].items[0]

        assert item.name == "Licuado receta"
        assert item.recipe_id == recipe_id
        assert item.food_product_id is None
        assert item.quantity == Decimal("1.000")
        assert item.unit == "serving"
        assert item.calories == Decimal("76.000")
        assert item.protein_g == Decimal("17.000")


def test_daily_nutrition_json_with_recipe_id_validates_and_imports(app, user):
    with app.app_context():
        recipe = _make_recipe(user, "Receta import nutrition")
        db.session.commit()

        document = build_daily_nutrition_document(
            user_id=user,
            record_date=date(2026, 7, 9),
            meal_type="breakfast",
            meal_name="Desayuno receta",
            item_name="Porción receta",
            recipe_id=recipe.id,
            quantity=Decimal("1.000"),
            unit="serving",
            calories=Decimal("76.000"),
            protein_g=Decimal("17.000"),
            fat_g=Decimal("0.400"),
            net_carbs_g=Decimal("0.000"),
            total_carbs_g=Decimal("0.000"),
            fiber_g=Decimal("0.000"),
            sodium_mg=Decimal("20.000"),
        )

        validate_json_document(document, "daily_nutrition")
        assert document["data"]["meals"][0]["items"][0]["recipe_id"] == recipe.id

        source_file, duplicate_file = generate_standard_json(
            document=document,
            schema_name="daily_nutrition",
            user_id=user,
            original_filename="daily_nutrition_recipe.json",
        )
        assert duplicate_file is False

        record, duplicate_record = import_daily_nutrition_file(source_file, user)
        assert duplicate_record is False
        item = record.meals[0].items[0]

        assert item.recipe_id == recipe.id
        assert item.food_product_id is None
        assert item.calories == Decimal("76.000")
        assert item.protein_g == Decimal("17.000")

        uploaded = db.session.get(UploadedFile, record.source_file_id)
        assert uploaded.detected_type == "daily_nutrition"


def test_daily_nutrition_rejects_recipe_id_from_other_user(app, user):
    with app.app_context():
        other = _make_user("other-recipe-nutrition-user")
        other_recipe = _make_recipe(other.id, "Other user's recipe")
        db.session.commit()

        document = build_daily_nutrition_document(
            user_id=user,
            record_date=date(2026, 7, 10),
            meal_type="snack",
            item_name="Invalid recipe item",
            recipe_id=other_recipe.id,
            quantity=Decimal("1.000"),
            unit="serving",
            calories=Decimal("10.000"),
        )

        source_file, _duplicate_file = generate_standard_json(
            document=document,
            schema_name="daily_nutrition",
            user_id=user,
            original_filename="bad_recipe_reference.json",
        )

        with pytest.raises(DailyNutritionImportError) as exc:
            import_daily_nutrition_file(source_file, user)

        assert "recipe_id does not belong to this user" in str(exc.value)