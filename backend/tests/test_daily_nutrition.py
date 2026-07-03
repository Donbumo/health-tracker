import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import DailyNutrition, NutritionItem, NutritionMeal, UploadedFile, User
from tests.conftest import login


def _item(name: str, calories: int, protein: int, fat: int, net: int, total: int, fiber: int, sugar: int, sodium: int) -> dict:
    return {
        "name": name,
        "quantity": 1,
        "unit": "serving",
        "calories_kcal": calories,
        "protein_g": protein,
        "fat_g": fat,
        "net_carbs_g": net,
        "total_carbs_g": total,
        "fiber_g": fiber,
        "sugar_g": sugar,
        "sodium_mg": sodium,
    }


def daily_nutrition_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": "2026-07-04",
            "source": "fictional-manual-log",
            "notes": "Fictional nutrition day",
            "calories_kcal": 9999,
            "meals": [
                {"meal_type": "breakfast", "name": "Breakfast", "items": [_item("Breakfast item", 300, 20, 10, 30, 35, 5, 5, 200)]},
                {"meal_type": "lunch", "name": "Lunch", "items": [_item("Lunch item", 500, 40, 20, 40, 45, 5, 4, 500)]},
                {"meal_type": "dinner", "name": "Dinner", "items": [_item("Dinner item", 400, 30, 15, 25, 30, 5, 3, 400)]},
                {"meal_type": "extra", "name": "Extra", "items": [_item("Extra item", 100, 5, 2, 10, 12, 2, 6, 100)]},
            ],
        },
    }


def _import_nutrition(client, document: dict, filename="nutrition.json"):
    return client.post(
        "/daily-nutrition/import",
        data={"file": (io.BytesIO(json.dumps(document).encode("utf-8")), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_import_nutrition_meals_recalculates_totals_and_deduplicates(app, client, user):
    login(client)
    document = daily_nutrition_document(user)
    response = _import_nutrition(client, document)
    assert response.status_code == 200

    with app.app_context():
        record = db.session.execute(db.select(DailyNutrition)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        record_id = record.id
        assert record.calories == Decimal("1300.000")
        assert record.protein_g == Decimal("95.000")
        assert record.fat_g == Decimal("47.000")
        assert record.net_carbs_g == Decimal("105.000")
        assert record.total_carbs_g == Decimal("122.000")
        assert record.fiber_g == Decimal("17.000")
        assert record.sugar_g == Decimal("18.000")
        assert record.sodium_mg == Decimal("1200.000")
        assert len(record.meals) == 4
        assert len(db.session.execute(db.select(NutritionMeal)).scalars().all()) == 4
        assert len(db.session.execute(db.select(NutritionItem)).scalars().all()) == 4
        assert source.detected_type == "daily_nutrition"
        assert source.import_status == "imported"

    _import_nutrition(client, document, "same-nutrition.json")
    with app.app_context():
        assert len(db.session.execute(db.select(DailyNutrition)).scalars().all()) == 1
        assert db.session.execute(db.select(UploadedFile)).scalar_one().import_status == "duplicate"
    assert client.get(f"/daily-nutrition/{record_id}").status_code == 200


def test_nutrition_supports_legacy_totals_and_rejects_invalid(app, client, user):
    login(client)
    legacy = {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user,
        "source_type": "uploaded",
        "data": {
            "date": "2026-07-05",
            "calories_kcal": 2100,
            "protein_g": 140,
            "carbohydrate_g": 220,
            "fat_g": 70,
        },
    }
    assert _import_nutrition(client, legacy).status_code == 200

    invalid = daily_nutrition_document(user)
    invalid["data"]["date"] = "2026-07-06"
    invalid["data"]["meals"][0]["items"][0]["protein_g"] = -1
    response = _import_nutrition(client, invalid, "invalid-nutrition.json")
    assert b"No fue posible importar" in response.data

    with app.app_context():
        record = db.session.execute(db.select(DailyNutrition)).scalar_one()
        assert record.calories == Decimal("2100.000")
        assert record.protein_g == Decimal("140.000")
        assert record.total_carbs_g == Decimal("220.000")
        assert record.net_carbs_g is None
        invalid_source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.import_status == "error")
        ).scalar_one()
        assert invalid_source.detected_type == "daily_nutrition"


def test_daily_nutrition_is_isolated_by_user(app, client, user):
    login(client)
    document = daily_nutrition_document(user)
    _import_nutrition(client, document)
    with app.app_context():
        record_id = db.session.execute(db.select(DailyNutrition.id)).scalar_one()
        second = User(username="nutrition-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    client.post("/logout")
    login(client, "nutrition-second-user", "second-password")
    assert client.get(f"/daily-nutrition/{record_id}").status_code == 404
    assert b"2026-07-04" not in client.get("/daily-nutrition").data
    rejected = _import_nutrition(client, document, "foreign-nutrition.json")
    assert b"does not belong to this user" in rejected.data
    with app.app_context():
        assert db.session.execute(
            db.select(DailyNutrition).where(DailyNutrition.user_id == second_id)
        ).scalar_one_or_none() is None
