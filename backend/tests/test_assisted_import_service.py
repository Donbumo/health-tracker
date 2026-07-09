"""Tests for read-only assisted import orchestration."""

from app.services.importers.assisted_import_service import AssistedImportService
from app.services.validation import validate_json_document


def _standard_recipe_document():
    return {
        "schema_version": "1.0",
        "type": "recipe",
        "name": "Receta demo",
        "servings": 1,
        "source": "manual",
        "ingredients": [
            {
                "food_product_name": "Producto demo",
                "quantity_g": 40,
            }
        ],
    }


def test_service_returns_standard_ready_for_official_schema(app):
    payload = _standard_recipe_document()

    with app.app_context():
        result = AssistedImportService().preview(payload, user_id=2)

    assert result["mode"] == "standard_ready"
    assert result["read_only"] is True
    assert result["schema_detection"]["mode"] == "standard"
    assert result["schema_detection"]["detected_type"] == "recipe"
    assert result["assistant_result"] is None
    assert result["selected_candidate"] is None
    assert result["standard_generation"] is None
    assert result["summary"]["generated_count"] == 0
    assert "import_with_standard_importer" in result["summary"]["actions_available"]


def test_service_generates_standard_weigh_in_json_from_assisted_payload(app):
    payload = {
        "metadata": {"source": "demo"},
        "registros": [
            {
                "fecha": "2026-07-05",
                "hora": "09:28",
                "peso_kg": "87.25",
                "grasa_corporal_pct": "27.3",
                "body_water_percent": "49.8",
                "musculo_kg": "60.19",
                "metabolismo_basal_kcal": "1788",
            }
        ],
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            requested_type="weigh_in",
            source_type="uploaded",
            default_timezone="-06:00",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["read_only"] is True
    assert result["selected_candidate"]["target_type"] == "weigh_in_batch"
    assert result["summary"]["generated_count"] == 1
    assert result["summary"]["valid_count"] == 1
    assert result["summary"]["invalid_count"] == 0

    generated = result["standard_generation"]["generated_documents"][0]
    assert generated["record_type"] == "weigh_in"
    assert generated["user_id"] == 2
    assert generated["source_type"] == "uploaded"

    data = generated["data"]
    assert data["recorded_at"] == "2026-07-05T09:28:00-06:00"
    assert data["weight_kg"] == 87.25
    assert data["body_fat_percent"] == 27.3
    assert data["water_percent"] == 49.8
    assert "body_water_percent" not in data

    validate_json_document(generated, "weigh_in")


def test_service_generates_standard_food_product_json(app):
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
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            target_type="food_products",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["selected_candidate"]["target_type"] == "food_products"
    assert result["summary"]["generated_count"] == 1
    assert result["summary"]["valid_count"] == 1

    generated = result["standard_generation"]["generated_documents"][0]
    assert generated["type"] == "food_product"
    assert generated["user_id"] == 2
    assert generated["name"] == "Producto demo"
    assert generated["brand"] == "Marca demo"
    assert generated["protein_g_per_100g"] == 85
    assert generated["source"] == "assisted_import"

    validate_json_document(generated, "food_product")


def test_service_returns_without_candidates_for_unknown_payload(app):
    payload = {
        "random": {
            "foo": "bar",
            "baz": 123,
        }
    }

    with app.app_context():
        result = AssistedImportService().preview(payload, user_id=2)

    assert result["mode"] == "assistant_required_without_candidates"
    assert result["read_only"] is True
    assert result["selected_candidate"] is None
    assert result["standard_generation"] is None
    assert result["summary"]["candidate_count"] == 0
    assert result["summary"]["generated_count"] == 0


def test_service_generates_standard_recipe_bundle_from_assisted_payload(app):
    payload = {
        "recetas": [
            {
                "nombre": "Receta demo",
                "porciones": 1,
                "ingredientes": [
                    {
                        "nombre": "Producto demo",
                        "cantidad_g": 40,
                    }
                ],
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            target_type="recipe_bundle",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["read_only"] is True
    assert result["selected_candidate"]["target_type"] == "recipe_bundle"
    assert result["standard_generation"]["schema_name"] == "recipe_bundle"
    assert result["summary"]["generated_count"] == 1
    assert result["summary"]["valid_count"] == 1

    document = result["standard_generation"]["generated_documents"][0]
    assert document["type"] == "recipe_bundle"
    assert document["user_id"] == 2
    assert document["recipes"][0]["name"] == "Receta demo"
    assert document["recipes"][0]["ingredients"][0]["food_product_name"] == "Producto demo"
    assert document["recipes"][0]["ingredients"][0]["quantity_g"] == 40

    validate_json_document(document, "recipe_bundle")


def test_service_can_skip_standard_generation(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
                "body_water_percent": 49.8,
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            requested_type="weigh_in",
            generate_standard_json=False,
        )

    assert result["mode"] == "assistant_preview_ready"
    assert result["selected_candidate"]["target_type"] == "weigh_in_batch"
    assert result["standard_generation"] is None
    assert result["summary"]["generated_count"] == 0


def test_service_reports_validation_errors_from_generated_documents(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "body_water_percent": 49.8,
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            requested_type="weigh_in",
        )

    assert result["mode"] == "standard_json_generated_with_errors"
    assert result["summary"]["generated_count"] == 1
    assert result["summary"]["valid_count"] == 0
    assert result["summary"]["invalid_count"] == 1

    errors = result["standard_generation"]["validated_documents"][0]["errors"]
    assert any("weight_kg" in error for error in errors)


def test_service_returns_no_candidate_when_requested_target_does_not_match(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=2,
            target_type="food_products",
        )

    assert result["mode"] == "assistant_required_without_candidates"
    assert result["selected_candidate"] is None
    assert result["standard_generation"] is None
    assert any(
        "No candidate matched" in warning
        for warning in result["summary"]["warnings"]
    )


def test_service_generates_standard_daily_energy_json_from_assisted_payload(app):
    """Service orchestrates detection -> mapping -> generation for daily_energy."""
    payload = {
        "energia": [
            {
                "fecha": "2026-07-10",
                "calorias_totales": "2400",
                "calorias_activas": "700",
                "calorias_reposo": "1700",
                "pasos": "11000",
                "distancia": "8.5",
            },
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=5,
            requested_type="daily_energy",
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["read_only"] is True
    assert result["target_type"] == "daily_energy"
    assert result["selected_candidate"] is not None
    assert result["selected_candidate"]["target_type"] == "daily_energy"

    generation = result["standard_generation"]
    assert generation is not None
    assert generation["schema_name"] == "daily_energy"
    assert generation["records_detected"] == 1
    assert generation["validated_documents"][0]["valid"] is True

    document = generation["generated_documents"][0]
    assert document["schema_version"] == "1.0"
    assert document["record_type"] == "daily_energy"
    assert document["user_id"] == 5
    assert document["source_type"] == "uploaded"

    data = document["data"]
    assert data["date"] == "2026-07-10"
    assert data["total_expenditure_kcal"] == 2400
    assert data["active_expenditure_kcal"] == 700
    assert data["resting_expenditure_kcal"] == 1700
    assert data["steps"] == 11000
    assert data["distance_meters"] == 8500.0

    summary = result["summary"]
    assert summary["valid_count"] == 1
    assert summary["invalid_count"] == 0
    assert "import_with_standard_importer_later" in summary["actions_available"]

    validate_json_document(document, "daily_energy")


def test_service_generates_standard_daily_nutrition_json_from_assisted_payload(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-10",
                "calorias": "2100",
                "proteina_g": "140",
                "desayuno": [
                    {
                        "nombre": "Fictional breakfast item",
                        "kcal": "350",
                    }
                ],
            },
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=5,
            requested_type="daily_nutrition",
            source_type="manual_generated",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["read_only"] is True
    assert result["target_type"] == "daily_nutrition"
    assert result["selected_candidate"] is not None
    assert result["selected_candidate"]["target_type"] == "daily_nutrition"

    generation = result["standard_generation"]
    assert generation is not None
    assert generation["schema_name"] == "daily_nutrition"
    assert generation["records_detected"] == 1
    assert generation["validated_documents"][0]["valid"] is True

    document = generation["generated_documents"][0]
    assert document["schema_version"] == "1.0"
    assert document["record_type"] == "daily_nutrition"
    assert document["user_id"] == 5
    assert document["source_type"] == "manual_generated"

    data = document["data"]
    assert data["date"] == "2026-07-10"
    assert data["calories_kcal"] == 2100
    assert data["protein_g"] == 140
    assert data["meals"][0]["meal_type"] == "breakfast"
    assert data["meals"][0]["items"][0]["name"] == "Fictional breakfast item"
    assert data["meals"][0]["items"][0]["calories_kcal"] == 350

    summary = result["summary"]
    assert summary["valid_count"] == 1
    assert summary["invalid_count"] == 0
    assert "import_with_standard_importer_later" in summary["actions_available"]

    validate_json_document(document, "daily_nutrition")


def test_service_generates_standard_completed_workout_json_from_assisted_payload(app):
    payload = {
        "entrenamientos": [
            {
                "fecha": "2026-07-13",
                "hora": "07:15",
                "training_plan_id": 20,
                "training_plan_version_id": 21,
                "planned_week_number": 4,
                "planned_day_number": 3,
                "rutina": "Upper demo",
                "ejercicios": [
                    {
                        "nombre": "Press demo",
                        "series": [
                            {
                                "peso": "80",
                                "reps": "8",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=5,
            requested_type="completed_workout",
            source_type="uploaded",
            default_timezone="-06:00",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["read_only"] is True
    assert result["target_type"] == "completed_workout"
    assert result["summary"]["generated_count"] == 1
    assert result["summary"]["valid_count"] == 1
    assert result["summary"]["invalid_count"] == 0

    document = result["standard_generation"]["generated_documents"][0]
    assert document["record_type"] == "completed_workout"
    assert document["user_id"] == 5

    data = document["data"]
    assert data["training_plan_id"] == 20
    assert data["training_plan_version_id"] == 21
    assert data["planned_week_number"] == 4
    assert data["planned_day_number"] == 3
    assert data["performed_at"] == "2026-07-13T07:15:00-06:00"
    assert data["exercises"][0]["name"] == "Press demo"
    assert data["exercises"][0]["sets"][0]["weight_kg"] == 80.0
    assert data["exercises"][0]["sets"][0]["reps"] == 8

    validate_json_document(document, "completed_workout")


def test_service_generates_standard_medical_lab_json_from_assisted_payload(app):
    """Service orchestrates detection -> mapping -> generation for medical_lab."""
    payload = {
        "labs": [
            {
                "laboratorio": "Laboratorio Demo C",
                "fecha": "2026-07-20",
                "marcadores": [
                    {"nombre": "Glucosa", "valor": "85", "unidad": "mg/dL"}
                ]
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=7,
            requested_type="medical_lab",
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "medical_lab"

    generation = result["standard_generation"]
    assert generation is not None
    assert generation["schema_name"] == "medical_lab"
    assert generation["validated_documents"][0]["valid"] is True

    document = generation["generated_documents"][0]
    assert document["type"] == "medical_lab"
    assert document["user_id"] == 7
    assert document["laboratory_name"] == "Laboratorio Demo C"
    assert document["date"] == "2026-07-20"

    markers = document["markers"]
    assert len(markers) == 1
    assert markers[0]["name"] == "Glucosa"
    assert markers[0]["value"] == 85.0
    assert markers[0]["unit"] == "mg/dL"

    validate_json_document(document, "medical_lab")


def test_service_generates_standard_training_plan_json_from_assisted_payload(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina demo QA",
                "semanas": [
                    {
                        "semana": 1,
                        "dias": [
                            {
                                "dia": 1,
                                "nombre": "Día demo",
                                "ejercicios": [
                                    {
                                        "orden": 1,
                                        "nombre": "Press demo",
                                        "series": [{"serie": 1, "reps": 8}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=7,
            requested_type="training_plan",
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "training_plan"
    assert result["summary"]["valid_count"] == 1

    document = result["standard_generation"]["generated_documents"][0]
    assert document["record_type"] == "training_plan"
    assert document["user_id"] == 7
    assert document["data"]["weeks"][0]["days"][0]["exercises"][0]["name"] == "Press demo"

    validate_json_document(document, "training_plan")


def test_service_generates_standard_recipe_json_from_assisted_payload(app):
    payload = {
        "receta": {
            "nombre": "Receta demo QA",
            "ingredientes": [
                {
                    "producto": "Producto demo QA",
                    "cantidad_g": 25,
                }
            ],
        }
    }

    with app.app_context():
        result = AssistedImportService().preview(
            payload,
            user_id=7,
            requested_type="recipe",
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "recipe"
    assert result["summary"]["valid_count"] == 1

    document = result["standard_generation"]["generated_documents"][0]
    assert document["type"] == "recipe"
    assert document["user_id"] == 7
    assert document["ingredients"][0]["food_product_name"] == "Producto demo QA"

    validate_json_document(document, "recipe")
