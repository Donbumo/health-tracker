import csv
import io
import json

import pytest

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, User
from app.services.exporters import ExportError
from app.services.exporters.wellness import (
    DailyEnergyJsonExporter,
    DailyNutritionCsvExporter,
)
from app.services.validation import validate_json_document
from tests.conftest import login


def _create_manual_records(client):
    client.post(
        "/manual/energy",
        data={
            "date": "2026-07-08",
            "total_calories": "2300",
            "active_calories": "500",
            "steps": "7000",
        },
    )
    client.post(
        "/manual/nutrition",
        data={
            "date": "2026-07-08",
            "meal_type": "dinner",
            "item_name": "Fictional export item",
            "quantity": "1",
            "unit": "serving",
            "calories": "650",
            "protein_g": "45",
            "fat_g": "20",
            "net_carbs_g": "55",
            "fiber_g": "8",
        },
    )


def test_wellness_export_services_and_http(app, client, user):
    login(client)
    _create_manual_records(client)
    with app.app_context():
        energy = db.session.execute(db.select(DailyEnergy)).scalar_one()
        nutrition = db.session.execute(db.select(DailyNutrition)).scalar_one()
        energy_id = energy.id
        nutrition_id = nutrition.id

        energy_artifact = DailyEnergyJsonExporter().export(energy, user)
        energy_document = json.loads(energy_artifact.content)
        validate_json_document(energy_document, "daily_energy")
        assert energy_document["data"]["total_expenditure_kcal"] == 2300

        nutrition_csv = DailyNutritionCsvExporter().export(nutrition, user)
        rows = list(
            csv.DictReader(io.StringIO(nutrition_csv.content.decode("utf-8-sig")))
        )
        assert rows[0]["calories"] == "650.000"
        assert nutrition_csv.warning is not None

    energy_json = client.get(f"/daily-energy/{energy_id}/export/json")
    assert energy_json.status_code == 200
    assert energy_json.mimetype == "application/json"
    validate_json_document(json.loads(energy_json.data), "daily_energy")

    energy_csv = client.get(f"/daily-energy/{energy_id}/export/csv")
    assert energy_csv.status_code == 200
    assert b"total_calories" in energy_csv.data

    nutrition_json = client.get(f"/daily-nutrition/{nutrition_id}/export/json")
    assert nutrition_json.status_code == 200
    document = json.loads(nutrition_json.data)
    validate_json_document(document, "daily_nutrition")
    assert document["data"]["meals"][0]["items"][0]["name"] == "Fictional export item"

    nutrition_csv = client.get(f"/daily-nutrition/{nutrition_id}/export/csv")
    assert nutrition_csv.status_code == 200
    assert b"protein_g" in nutrition_csv.data


def test_wellness_exports_are_isolated_by_user(app, client, user):
    login(client)
    _create_manual_records(client)
    with app.app_context():
        energy = db.session.execute(db.select(DailyEnergy)).scalar_one()
        nutrition = db.session.execute(db.select(DailyNutrition)).scalar_one()
        energy_id = energy.id
        nutrition_id = nutrition.id
        second = User(username="wellness-export-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        with pytest.raises(ExportError):
            DailyEnergyJsonExporter().export(energy, second_id)
        with pytest.raises(ExportError):
            DailyNutritionCsvExporter().export(nutrition, second_id)

    client.post("/logout")
    login(client, "wellness-export-second", "second-password")
    assert client.get(f"/daily-energy/{energy_id}/export/json").status_code == 404
    assert client.get(f"/daily-energy/{energy_id}/export/csv").status_code == 404
    assert client.get(f"/daily-nutrition/{nutrition_id}/export/json").status_code == 404
    assert client.get(f"/daily-nutrition/{nutrition_id}/export/csv").status_code == 404
