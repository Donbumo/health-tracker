"""Tests for read-only standard JSON generation from assisted mappings."""

from app.services.importers.standard_json_generator import StandardJsonGenerator
from app.services.importers.universal_json_import_assistant import (
    UniversalJsonImportAssistant,
)
from app.services.validation import validate_json_document


def _primary_candidate(payload, requested_type=None):
    result = UniversalJsonImportAssistant().analyze(
        payload,
        requested_type=requested_type,
    )
    assert result["mode"] == "assistant_required"
    assert result["preview"]["primary_candidate"] is not None
    return result["preview"]["primary_candidate"]


def test_generate_weigh_in_documents_from_assisted_candidate(app):
    payload = {
        "metadata": {"source": "demo"},
        "registros": [
            {
                "fecha": "2026-07-05",
                "hora": "09:28:00",
                "peso_kg": "87.25",
                "grasa_corporal_pct": "27.3",
                "body_water_percent": "49.8",
                "musculo_kg": "60.19",
                "metabolismo_basal_kcal": "1788",
            }
        ],
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="weigh_in")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "weigh_in_batch"
    assert result["schema_name"] == "weigh_in"
    assert result["records_detected"] == 1
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["schema_version"] == "1.0"
    assert document["record_type"] == "weigh_in"
    assert document["user_id"] == 2
    assert document["source_type"] == "uploaded"

    data = document["data"]
    assert data["recorded_at"] == "2026-07-05T09:28:00+00:00"
    assert data["weight_kg"] == 87.25
    assert data["body_fat_percent"] == 27.3
    assert data["water_percent"] == 49.8
    assert data["muscle_mass_kg"] == 60.19
    assert data["bmr_kcal"] == 1788
    assert "body_water_percent" not in data

    validate_json_document(document, "weigh_in")


def test_generate_weigh_in_documents_adds_midnight_for_date_only(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
                "water_percentage": 49.8,
            }
        ],
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="weigh_in")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
            default_timezone="-06:00",
        )

    document = result["generated_documents"][0]
    assert document["data"]["recorded_at"] == "2026-07-05T00:00:00-06:00"
    assert document["data"]["water_percent"] == 49.8
    assert result["validated_documents"][0]["valid"] is True


def test_generate_weigh_in_documents_reports_validation_errors(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "body_water_percent": 49.8,
            }
        ],
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="weigh_in")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
        )

    assert result["validated_documents"][0]["valid"] is False
    assert any(
        "weight_kg" in error
        for error in result["validated_documents"][0]["errors"]
    )


def test_generate_food_product_documents_from_assisted_candidate(app):
    payload = {
        "alacena": [
            {
                "nombre": "Producto demo",
                "marca": "Marca demo",
                "kcal": "380",
                "proteina_g": "85",
                "grasa_g": "2",
                "carbohidratos": "0",
                "carbos_netos_g": "0",
                "fibra_g": "0",
                "sodio_mg": "100",
            },
            {
                "nombre": "Producto demo 2",
                "marca": "Marca demo",
                "kcal": "120",
                "proteina_g": "10",
                "grasa_g": "5",
                "carbohidratos": "3",
                "carbos_netos_g": "2",
                "fibra_g": "1",
                "sodio_mg": "90",
            },
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload)
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "food_products"
    assert result["schema_name"] == "food_product"
    assert result["records_detected"] == 2
    assert all(item["valid"] for item in result["validated_documents"])

    first = result["generated_documents"][0]
    assert first["schema_version"] == "1.0"
    assert first["type"] == "food_product"
    assert first["user_id"] == 2
    assert first["source_type"] == "uploaded"
    assert first["source"] == "assisted_import"
    assert first["name"] == "Producto demo"
    assert first["brand"] == "Marca demo"
    assert first["calories_per_100g"] == 380
    assert first["protein_g_per_100g"] == 85
    assert first["fat_g_per_100g"] == 2
    assert first["carbs_g_per_100g"] == 0
    assert first["net_carbs_g_per_100g"] == 0
    assert first["fiber_g_per_100g"] == 0
    assert first["sodium_mg_per_100g"] == 100

    validate_json_document(first, "food_product")


def test_generate_food_product_documents_reports_missing_name(app):
    payload = {
        "alacena": [
            {
                "marca": "Marca demo",
                "kcal": 380,
                "proteina_g": 85,
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload)
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
        )

    assert result["validated_documents"][0]["valid"] is False
    assert any(
        "name" in error
        for error in result["validated_documents"][0]["errors"]
    )


def test_generator_returns_unsupported_for_non_implemented_target(app):
    payload = {
        "recetas": [
            {
                "nombre": "Receta demo",
                "ingredientes": [],
            }
        ]
    }
    candidate = {
        "target_type": "recipe_bundle",
        "path": "recetas",
        "suggested_mapping": {"nombre": "name"},
    }

    with app.app_context():
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
        )

    assert result["mode"] == "unsupported_target"
    assert result["target_type"] == "recipe_bundle"
    assert result["generated_documents"] == []
    assert result["validated_documents"] == []


# ---------------------------------------------------------------------------
# daily_energy generation tests
# ---------------------------------------------------------------------------

def test_generate_daily_energy_documents_from_assisted_candidate(app):
    """Generator maps Spanish aliases to canonical daily_energy schema fields."""
    payload = {
        "energia": [
            {
                "fecha": "2026-07-05",
                "calorias_totales": "2500",
                "calorias_activas": "600",
                "calorias_reposo": "1900",
                "pasos": "9800",
                "distancia": "7.2",
            },
            {
                "fecha": "2026-07-06",
                "calorias_totales": "2100",
                "pasos": "5000",
            },
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_energy")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=3,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "daily_energy"
    assert result["schema_name"] == "daily_energy"
    assert result["records_detected"] == 2
    assert all(item["valid"] for item in result["validated_documents"])

    first = result["generated_documents"][0]
    assert first["schema_version"] == "1.0"
    assert first["record_type"] == "daily_energy"
    assert first["user_id"] == 3
    assert first["source_type"] == "uploaded"

    data = first["data"]
    assert data["date"] == "2026-07-05"
    assert data["total_expenditure_kcal"] == 2500
    assert data["active_expenditure_kcal"] == 600
    assert data["resting_expenditure_kcal"] == 1900
    assert data["steps"] == 9800
    # distance_km 7.2 -> 7200.0 meters
    assert data["distance_meters"] == 7200.0

    validate_json_document(first, "daily_energy")

    second = result["generated_documents"][1]
    assert second["data"]["date"] == "2026-07-06"
    assert second["data"]["total_expenditure_kcal"] == 2100
    assert second["data"]["steps"] == 5000


def test_generate_daily_energy_documents_with_english_aliases(app):
    """Generator accepts English aliases like total_calories, active_energy."""
    payload = {
        "watch": [
            {
                "date": "2026-07-07",
                "total_calories": 2300,
                "active_energy": 550,
                "resting_energy": 1750,
                "steps": 8000,
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_energy")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=3,
            source_type="device_sync",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["validated_documents"][0]["valid"] is True

    data = result["generated_documents"][0]["data"]
    assert data["date"] == "2026-07-07"
    assert data["total_expenditure_kcal"] == 2300
    assert data["active_expenditure_kcal"] == 550
    assert data["resting_expenditure_kcal"] == 1750
    assert data["steps"] == 8000


def test_generate_daily_energy_document_missing_date_fails_validation(app):
    """A record missing the required date field produces an invalid document."""
    payload = {
        "energia": [
            {
                "calorias_totales": 2000,
                "pasos": 5000,
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_energy")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=3,
        )

    # Document is generated but schema validation fails (date is required)
    assert result["validated_documents"][0]["valid"] is False
    assert any("date" in e for e in result["validated_documents"][0]["errors"])
