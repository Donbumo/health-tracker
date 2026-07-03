import json
from decimal import Decimal

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, UploadedFile
from app.services.validation import validate_json_document
from tests.conftest import login


def test_manual_energy_generates_valid_json_and_persists(app, client, user):
    login(client)
    form_data = {
        "date": "2026-07-07",
        "total_calories": "2400.5",
        "active_calories": "600.5",
        "resting_calories": "1800",
        "steps": "8500",
        "distance_meters": "6500",
        "notes": "Fictional manual energy",
    }
    response = client.post("/manual/energy", data=form_data, follow_redirects=True)
    assert response.status_code == 200
    assert b"2400.50" in response.data

    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        assert record.user_id == user
        assert record.total_calories == Decimal("2400.50")
        assert source.source_type == "manual_generated"
        assert source.detected_type == "daily_energy"
        assert source.import_status == "imported"
        assert source.storage_path.startswith(f"uploads/generated/user_{user}/")
        document = json.loads(
            (app.config["DATA_ROOT"] / source.storage_path).read_text("utf-8")
        )
        validate_json_document(document, "daily_energy")
        assert document["data"]["steps"] == 8500

    duplicate = client.post("/manual/energy", data=form_data, follow_redirects=True)
    assert b"ya exist" in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(DailyEnergy)).scalars().all()) == 1
        assert db.session.execute(db.select(UploadedFile)).scalar_one().import_status == "duplicate"


def test_manual_energy_requires_at_least_one_metric(app, client, user):
    login(client)
    response = client.post("/manual/energy", data={"date": "2026-07-07"})
    assert response.status_code == 200
    assert "Ingresa al menos una métrica.".encode() in response.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None
        assert db.session.execute(db.select(UploadedFile)).scalar_one_or_none() is None


def test_manual_nutrition_generates_item_json_and_calculated_totals(
    app,
    client,
    user,
):
    login(client)
    form_data = {
        "date": "2026-07-07",
        "meal_type": "breakfast",
        "meal_name": "Fictional breakfast",
        "item_name": "Fictional item",
        "quantity": "1.5",
        "unit": "serving",
        "calories": "350",
        "protein_g": "25",
        "fat_g": "12",
        "net_carbs_g": "30",
        "total_carbs_g": "35",
        "fiber_g": "5",
        "sugar_g": "6",
        "sodium_mg": "250",
        "notes": "Fictional manual nutrition",
    }
    response = client.post(
        "/manual/nutrition",
        data=form_data,
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Fictional item" in response.data

    with app.app_context():
        record = db.session.execute(db.select(DailyNutrition)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        assert record.user_id == user
        assert record.calories == Decimal("350.000")
        assert record.protein_g == Decimal("25.000")
        assert record.meals[0].items[0].quantity == Decimal("1.500")
        assert source.source_type == "manual_generated"
        assert source.detected_type == "daily_nutrition"
        document = json.loads(
            (app.config["DATA_ROOT"] / source.storage_path).read_text("utf-8")
        )
        validate_json_document(document, "daily_nutrition")
        assert document["data"]["meals"][0]["items"][0]["protein_g"] == 25
