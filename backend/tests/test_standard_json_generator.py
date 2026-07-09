"""Tests for read-only standard JSON generation from assisted mappings."""

from app.services.importers.standard_json_generator import (
    SUPPORTED_TARGETS,
    StandardJsonGenerator,
)
from app.services.importers.schema_detector import SchemaDetector
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


def test_generator_returns_unsupported_for_unknown_target(app):
    payload = {
        "recetas": [
            {
                "nombre": "Receta demo",
                "ingredientes": [],
            }
        ]
    }
    candidate = {
        "target_type": "future_target",
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
    assert result["target_type"] == "future_target"
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

    assert result["validated_documents"][0]["valid"] is False
    assert any("date" in e for e in result["validated_documents"][0]["errors"])


# ---------------------------------------------------------------------------
# daily_nutrition generation tests
# ---------------------------------------------------------------------------


def test_generate_daily_nutrition_flat_document_from_assisted_candidate(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-05",
                "calorias": "2100",
                "proteina_g": "140",
                "grasa_g": "70",
                "carbohidratos": "180",
                "carbos_netos_g": "150",
                "fibra_g": "30",
                "azucares_g": "20",
                "sodio_mg": "1800",
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=9,
            source_type="device_sync",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "daily_nutrition"
    assert result["schema_name"] == "daily_nutrition"
    assert result["records_detected"] == 1
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["schema_version"] == "1.0"
    assert document["record_type"] == "daily_nutrition"
    assert document["user_id"] == 9
    assert document["source_type"] == "device_sync"

    data = document["data"]
    assert data["date"] == "2026-07-05"
    assert data["calories_kcal"] == 2100
    assert data["protein_g"] == 140
    assert data["fat_g"] == 70
    assert data["total_carbs_g"] == 180
    assert data["net_carbs_g"] == 150
    assert data["fiber_g"] == 30
    assert data["sugar_g"] == 20
    assert data["sodium_mg"] == 1800
    assert "calories" not in data
    assert "carbs_g" not in data
    assert "sugars_g" not in data

    validate_json_document(document, "daily_nutrition")


def test_generate_daily_nutrition_nested_meals_from_assisted_candidate(app):
    payload = {
        "nutrition": [
            {
                "date": "2026-07-06",
                "meals": [
                    {
                        "meal_type": "breakfast",
                        "name": "Fictional breakfast",
                        "items": [
                            {
                                "name": "Fictional oats",
                                "quantity": "80",
                                "unit": "g",
                                "calories": "300",
                                "protein_g": "18",
                                "sugars_g": "6",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=9,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    meal = document["data"]["meals"][0]
    assert meal["meal_type"] == "breakfast"
    assert meal["name"] == "Fictional breakfast"

    item = meal["items"][0]
    assert item["name"] == "Fictional oats"
    assert item["quantity"] == 80
    assert item["unit"] == "g"
    assert item["calories_kcal"] == 300
    assert item["protein_g"] == 18
    assert item["sugar_g"] == 6

    validate_json_document(document, "daily_nutrition")


def test_generate_daily_nutrition_batch_documents(app):
    payload = {
        "nutrition": [
            {"fecha": "2026-07-07", "calorias": "2000"},
            {"fecha": "2026-07-08", "calorias": "2200", "proteina_g": "150"},
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)

    assert result["records_detected"] == 2
    assert len(result["generated_documents"]) == 2
    assert all(item["valid"] for item in result["validated_documents"])
    assert result["generated_documents"][0]["data"]["date"] == "2026-07-07"
    assert result["generated_documents"][1]["data"]["protein_g"] == 150


def test_generate_daily_nutrition_spanish_meal_sections(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-09",
                "desayuno": [
                    {
                        "nombre": "Yogurt ficticio",
                        "cantidad": "1",
                        "unidad": "serving",
                        "kcal": "180",
                    }
                ],
                "comida": [
                    {
                        "alimento": "Pollo ficticio",
                        "proteina_g": "45",
                    }
                ],
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)

    assert result["validated_documents"][0]["valid"] is True
    meals = result["generated_documents"][0]["data"]["meals"]
    assert meals[0]["meal_type"] == "breakfast"
    assert meals[0]["items"][0]["name"] == "Yogurt ficticio"
    assert meals[0]["items"][0]["calories_kcal"] == 180
    assert meals[1]["meal_type"] == "lunch"
    assert meals[1]["items"][0]["name"] == "Pollo ficticio"
    assert meals[1]["items"][0]["protein_g"] == 45


def test_generate_daily_nutrition_missing_date_fails_validation(app):
    payload = {
        "nutrition": [
            {
                "calorias": 2100,
                "proteina_g": 140,
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)

    assert result["validated_documents"][0]["valid"] is False
    assert any("date" in error for error in result["validated_documents"][0]["errors"])


def test_generate_daily_nutrition_missing_item_name_fails_validation(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-10",
                "desayuno": [
                    {
                        "calorias": 200,
                        "proteina_g": 20,
                    }
                ],
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)

    document = result["generated_documents"][0]
    item = document["data"]["meals"][0]["items"][0]
    assert "name" not in item
    assert result["validated_documents"][0]["valid"] is False
    assert any("name" in error for error in result["validated_documents"][0]["errors"])


def test_generate_daily_nutrition_warns_for_unknown_fields(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-11",
                "calorias": 2100,
                "campo_desconocido": "ignored",
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)

    assert result["validated_documents"][0]["valid"] is True
    assert any("campo_desconocido" in warning for warning in result["warnings"])


def test_generate_daily_nutrition_round_trips_through_schema_detection(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-12",
                "calorias": 2100,
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="daily_nutrition")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=9)
        document = result["generated_documents"][0]
        validate_json_document(document, "daily_nutrition")
        detection = SchemaDetector().detect(document, requested_type="daily_nutrition")

    assert detection["mode"] == "standard"
    assert detection["detected_type"] == "daily_nutrition"
    assert detection["schema_name"] == "daily_nutrition"


# ---------------------------------------------------------------------------
# completed_workout generation tests
# ---------------------------------------------------------------------------


def test_generate_completed_workout_documents_from_assisted_candidate(app):
    payload = {
        "entrenamientos": [
            {
                "fecha": "2026-07-12",
                "hora": "18:30",
                "training_plan_id": 10,
                "training_plan_version_id": 11,
                "planned_week_number": 3,
                "planned_day_number": 2,
                "rutina": "Full body demo",
                "duracion": "3600",
                "frecuencia_cardiaca": "120",
                "calorias": "450",
                "ejercicios": [
                    {
                        "nombre": "Sentadilla demo",
                        "series": [
                            {
                                "peso": "100",
                                "reps": "5",
                                "rir": "2",
                                "rpe": "8",
                                "descanso": "120",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="completed_workout")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
            source_type="uploaded",
            default_timezone="-06:00",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "completed_workout"
    assert result["schema_name"] == "completed_workout"
    assert result["records_detected"] == 1
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["record_type"] == "completed_workout"
    assert document["user_id"] == 2
    assert document["source_type"] == "uploaded"

    data = document["data"]
    assert data["training_plan_id"] == 10
    assert data["training_plan_version_id"] == 11
    assert data["planned_week_number"] == 3
    assert data["planned_day_number"] == 2
    assert data["performed_at"] == "2026-07-12T18:30:00-06:00"
    assert data["duration_seconds"] == 3600
    assert data["average_heart_rate_bpm"] == 120
    assert data["calories_burned"] == 450.0
    assert data["notes"] == "Session: Full body demo"

    exercise = data["exercises"][0]
    assert exercise["exercise_order"] == 1
    assert exercise["planned_exercise_order"] == 1
    assert exercise["name"] == "Sentadilla demo"

    workout_set = exercise["sets"][0]
    assert workout_set["set_number"] == 1
    assert workout_set["planned_set_number"] == 1
    assert workout_set["weight_kg"] == 100.0
    assert workout_set["reps"] == 5
    assert workout_set["rir"] == 2.0
    assert workout_set["rpe"] == 8.0
    assert workout_set["rest_seconds"] == 120

    validate_json_document(document, "completed_workout")


def test_generate_completed_workout_documents_missing_required_fields_fails_validation(app):
    payload = {
        "entrenamientos": [
            {
                "fecha": "2026-07-12",
                "rutina": "Full body demo",
                "ejercicios": [
                    {
                        "nombre": "Sentadilla demo",
                        "series": [
                            {
                                "peso": "100",
                                "reps": "5",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="completed_workout")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=2,
            default_timezone="-06:00",
        )

    document = result["generated_documents"][0]
    data = document["data"]

    assert "training_plan_id" not in data
    assert "training_plan_version_id" not in data
    assert "planned_week_number" not in data
    assert "planned_day_number" not in data
    assert result["validated_documents"][0]["valid"] is False

    errors = result["validated_documents"][0]["errors"]
    assert any("training_plan_id" in error for error in errors)
    assert any("training_plan_version_id" in error for error in errors)
    assert any("planned_week_number" in error for error in errors)
    assert any("planned_day_number" in error for error in errors)


# ---------------------------------------------------------------------------
# medical_lab generation tests
# ---------------------------------------------------------------------------

def test_generate_medical_lab_documents_with_nested_markers(app):
    """Generator extracts nested markers properly."""
    payload = {
        "labs": [
            {
                "laboratorio": "Laboratorio Demo A",
                "fecha": "2026-07-06",
                "marcadores": [
                    {"nombre": "Glucosa", "valor": "90", "unidad": "mg/dL", "estado": "normal", "rango_referencia": "70 - 100"},
                    {"marcador": "Insulina", "value": "12", "unit": "uU/mL"}
                ]
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="medical_lab")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=7,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "medical_lab"
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["date"] == "2026-07-06"
    assert document["laboratory_name"] == "Laboratorio Demo A"

    markers = document["markers"]
    assert len(markers) == 2
    assert markers[0]["name"] == "Glucosa"
    assert markers[0]["value"] == 90.0
    assert markers[0]["unit"] == "mg/dL"
    assert markers[0]["status"] == "normal"
    assert markers[0]["reference_text"] == "70 - 100"

    assert markers[1]["name"] == "Insulina"
    assert markers[1]["value"] == 12.0
    assert markers[1]["unit"] == "uU/mL"


def test_generate_medical_lab_documents_with_flat_markers(app):
    """Generator converts flat marker aliases into a markers array."""
    payload = {
        "labs": [
            {
                "lab_name": "Laboratorio Demo B",
                "lab_date": "2026-07-10",
                "glucosa": "95",
                "colesterol": {"valor": "180", "unidad": "mg/dL"}
            }
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="medical_lab")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=8,
            source_type="uploaded",
        )

    assert result["mode"] == "standard_json_generated"
    # Even if valid, note that flat markers missing units might fail schema validation.
    # The requirement is NOT to invent them. So if unit is missing for glucosa, it will fail validation.
    assert result["validated_documents"][0]["valid"] is False

    document = result["generated_documents"][0]
    assert document["laboratory_name"] == "Laboratorio Demo B"

    markers = document["markers"]
    assert len(markers) == 2

    # Glucosa is missing unit, so it's structurally incomplete but generated exactly as provided.
    glucosa_marker = next(m for m in markers if m["name"] == "glucose")
    assert glucosa_marker["value"] == 95.0
    assert "unit" not in glucosa_marker

    cholesterol_marker = next(m for m in markers if m["name"] == "total_cholesterol")
    assert cholesterol_marker["value"] == 180.0
    assert cholesterol_marker["unit"] == "mg/dL"


# ---------------------------------------------------------------------------
# phase 5B final target coverage tests
# ---------------------------------------------------------------------------


def test_supported_targets_include_final_phase_5b_set():
    assert SUPPORTED_TARGETS == {
        "weigh_in_batch",
        "food_products",
        "daily_energy",
        "daily_nutrition",
        "completed_workout",
        "medical_lab",
        "training_plan",
        "recipe",
        "recipe_bundle",
    }


def test_generate_training_plan_document_from_assisted_candidate(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina demo fuerza",
                "descripcion": "Plan ficticio para QA",
                "semanas": [
                    {
                        "semana": 1,
                        "dias": [
                            {
                                "dia": 1,
                                "nombre": "Día A",
                                "ejercicios": [
                                    {
                                        "orden": 1,
                                        "nombre": "Sentadilla demo",
                                        "series": [
                                            {
                                                "serie": 1,
                                                "reps": 5,
                                                "descanso": 120,
                                            }
                                        ],
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
        candidate = _primary_candidate(payload, requested_type="training_plan")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=4,
            source_type="manual_generated",
        )

    assert result["mode"] == "standard_json_generated"
    assert result["target_type"] == "training_plan"
    assert result["schema_name"] == "training_plan"
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["record_type"] == "training_plan"
    assert document["user_id"] == 4
    assert document["source_type"] == "manual_generated"

    data = document["data"]
    assert data["name"] == "Rutina demo fuerza"
    assert data["weeks"][0]["week_number"] == 1
    assert data["weeks"][0]["days"][0]["day_number"] == 1
    exercise = data["weeks"][0]["days"][0]["exercises"][0]
    assert exercise["exercise_order"] == 1
    assert exercise["name"] == "Sentadilla demo"
    assert exercise["sets"][0]["set_number"] == 1
    assert exercise["sets"][0]["reps"] == 5
    assert exercise["sets"][0]["rest_seconds"] == 120

    validate_json_document(document, "training_plan")


def test_generate_training_plan_missing_required_set_number_fails_validation(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina demo incompleta",
                "semanas": [
                    {
                        "semana": 1,
                        "dias": [
                            {
                                "dia": 1,
                                "nombre": "Día A",
                                "ejercicios": [
                                    {
                                        "orden": 1,
                                        "nombre": "Sentadilla demo",
                                        "series": [{"reps": 5}],
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
        candidate = _primary_candidate(payload, requested_type="training_plan")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=4)

    set_data = (
        result["generated_documents"][0]["data"]["weeks"][0]["days"][0]
        ["exercises"][0]["sets"][0]
    )
    assert "set_number" not in set_data
    assert result["validated_documents"][0]["valid"] is False
    assert any("set_number" in error for error in result["validated_documents"][0]["errors"])


def test_generate_training_plan_preserves_historical_aliases_without_inventing_fields(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina alias demo",
                "version": "v1",
                "bloques": [{"nombre": "Bloque ignorado"}],
                "semanas": [
                    {
                        "semana": 1,
                        "dias": [
                            {
                                "dia": 1,
                                "nombre": "Día A",
                                "ejercicios": [
                                    {
                                        "orden": 1,
                                        "nombre": "Press demo",
                                        "series_objetivo": [
                                            {
                                                "serie": 1,
                                                "reps_objetivo": 8,
                                                "descanso_objetivo": 90,
                                                "rir_objetivo": 2,
                                                "rpe_objetivo": 8,
                                            }
                                        ],
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
        candidate = _primary_candidate(payload, requested_type="training_plan")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=4)

    document = result["generated_documents"][0]
    set_data = document["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"][0]

    assert result["validated_documents"][0]["valid"] is True
    assert set_data["reps"] == 8
    assert set_data["rest_seconds"] == 90
    assert "rir" not in set_data
    assert "rpe" not in set_data
    assert any("version" in warning for warning in result["warnings"])
    assert any("blocks" in warning for warning in result["warnings"])
    assert any("rir" in warning for warning in result["warnings"])
    assert any("rpe" in warning for warning in result["warnings"])


def test_generate_recipe_document_from_assisted_candidate(app):
    payload = {
        "receta": {
            "nombre": "Receta demo",
            "porciones": "2",
            "ingredientes": [
                {
                    "producto": "Producto demo",
                    "marca": "Marca demo",
                    "cantidad_g": "40",
                    "orden": 1,
                }
            ],
        }
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="recipe")
        result = StandardJsonGenerator().generate(
            payload,
            candidate,
            user_id=6,
            source_type="converted",
        )

    assert result["target_type"] == "recipe"
    assert result["schema_name"] == "recipe"
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["type"] == "recipe"
    assert document["user_id"] == 6
    assert document["source_type"] == "converted"
    assert document["name"] == "Receta demo"
    assert document["servings"] == 2
    assert document["ingredients"][0]["food_product_name"] == "Producto demo"
    assert document["ingredients"][0]["food_product_brand"] == "Marca demo"
    assert document["ingredients"][0]["quantity_g"] == 40

    validate_json_document(document, "recipe")


def test_generate_recipe_missing_quantity_fails_validation(app):
    payload = {
        "receta": {
            "nombre": "Receta demo",
            "ingredientes": [{"producto": "Producto demo"}],
        }
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="recipe")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=6)

    ingredient = result["generated_documents"][0]["ingredients"][0]
    assert "quantity_g" not in ingredient
    assert result["validated_documents"][0]["valid"] is False
    assert any("quantity_g" in error for error in result["validated_documents"][0]["errors"])


def test_generate_recipe_bundle_document_from_recipe_list(app):
    payload = {
        "recetas": [
            {
                "nombre": "Receta demo A",
                "ingredientes": [{"producto": "Producto demo A", "cantidad_g": 40}],
            },
            {
                "nombre": "Receta demo B",
                "ingredientes": [{"producto": "Producto demo B", "cantidad_g": 50}],
            },
        ]
    }

    with app.app_context():
        candidate = _primary_candidate(payload, requested_type="recipe_bundle")
        result = StandardJsonGenerator().generate(payload, candidate, user_id=6)

    assert result["target_type"] == "recipe_bundle"
    assert result["schema_name"] == "recipe_bundle"
    assert result["records_detected"] == 2
    assert len(result["generated_documents"]) == 1
    assert result["validated_documents"][0]["valid"] is True

    document = result["generated_documents"][0]
    assert document["type"] == "recipe_bundle"
    assert document["user_id"] == 6
    assert [recipe["name"] for recipe in document["recipes"]] == [
        "Receta demo A",
        "Receta demo B",
    ]

    validate_json_document(document, "recipe_bundle")


def test_training_plan_parent_path_with_indices_keeps_plan_metadata(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina con metadata",
                "descripcion": "Debe conservarse desde el padre",
                "semanas": [
                    {
                        "semana": 1,
                        "dias": [
                            {
                                "dia": 1,
                                "nombre": "Día índice",
                                "ejercicios": [
                                    {
                                        "orden": 1,
                                        "nombre": "Press índice",
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
    candidate = {
        "target_type": "training_plan",
        "path": "rutinas[0].semanas[0].dias[0].ejercicios[0].series",
        "suggested_mapping": {
            "nombre": "name",
            "descripcion": "description",
            "semanas": "weeks",
            "semana": "week_number",
            "dias": "days",
            "dia": "day_number",
            "ejercicios": "exercises",
            "orden": "exercise_order",
            "series": "sets",
            "serie": "set_number",
            "reps": "reps",
        },
    }

    with app.app_context():
        result = StandardJsonGenerator().generate(payload, candidate, user_id=4)

    document = result["generated_documents"][0]
    assert result["validated_documents"][0]["valid"] is True
    assert document["data"]["name"] == "Rutina con metadata"
    assert document["data"]["description"] == "Debe conservarse desde el padre"
    validate_json_document(document, "training_plan")


def test_recipe_parent_path_with_indices_keeps_recipe_metadata(app):
    payload = {
        "paquetes": [
            {
                "recetas": [
                    {
                        "nombre": "Receta con metadata",
                        "porciones": 3,
                        "ingredientes": [
                            {"producto": "Producto índice", "cantidad_g": 40}
                        ],
                    }
                ]
            }
        ]
    }
    candidate = {
        "target_type": "recipe",
        "path": "paquetes[0].recetas[0].ingredientes",
        "suggested_mapping": {
            "nombre": "name",
            "porciones": "servings",
            "ingredientes": "ingredients",
            "producto": "food_product_name",
            "cantidad_g": "quantity_g",
        },
    }

    with app.app_context():
        result = StandardJsonGenerator().generate(payload, candidate, user_id=6)

    document = result["generated_documents"][0]
    assert result["validated_documents"][0]["valid"] is True
    assert document["name"] == "Receta con metadata"
    assert document["servings"] == 3
    assert document["ingredients"][0]["food_product_name"] == "Producto índice"
    validate_json_document(document, "recipe")


def test_recipe_bundle_parent_path_with_indices_keeps_bundle_metadata_and_siblings(app):
    payload = {
        "paquetes": [
            {
                "nombre": "Bundle con metadata",
                "recetas": [
                    {
                        "nombre": "Receta índice A",
                        "ingredientes": [{"producto": "Producto A", "cantidad_g": 40}],
                    },
                    {
                        "nombre": "Receta índice B",
                        "ingredientes": [{"producto": "Producto B", "cantidad_g": 50}],
                    },
                ],
            }
        ]
    }
    candidate = {
        "target_type": "recipe_bundle",
        "path": "paquetes[0].recetas[0].ingredientes",
        "suggested_mapping": {
            "nombre": "name",
            "recetas": "recipes",
            "ingredientes": "ingredients",
            "producto": "food_product_name",
            "cantidad_g": "quantity_g",
        },
    }

    with app.app_context():
        result = StandardJsonGenerator().generate(payload, candidate, user_id=6)

    document = result["generated_documents"][0]
    assert result["validated_documents"][0]["valid"] is True
    assert document["name"] == "Bundle con metadata"
    assert [recipe["name"] for recipe in document["recipes"]] == [
        "Receta índice A",
        "Receta índice B",
    ]
    validate_json_document(document, "recipe_bundle")


def test_autodetects_recipe_recipe_bundle_and_nested_training_plan_without_requested_type(app):
    assistant = UniversalJsonImportAssistant()
    recipe_payload = {
        "receta": {
            "nombre": "Receta auto",
            "ingredientes": [{"producto": "Producto auto", "cantidad_g": 40}],
        }
    }
    recipe_list_payload = {
        "recetas": [
            {
                "nombre": "Receta lista",
                "ingredientes": [{"producto": "Producto lista", "cantidad_g": 40}],
            }
        ]
    }
    bundle_payload = {
        "bundle": {
            "nombre": "Bundle auto",
            "recetas": [
                {
                    "nombre": "Receta bundle",
                    "ingredientes": [{"producto": "Producto bundle", "cantidad_g": 40}],
                }
            ],
        }
    }
    training_payload = {
        "contenedor": {
            "rutinas": [
                {
                    "nombre": "Rutina auto",
                    "semanas": [
                        {
                            "semana": 1,
                            "dias": [
                                {
                                    "dia": 1,
                                    "nombre": "Día auto",
                                    "ejercicios": [
                                        {
                                            "orden": 1,
                                            "nombre": "Press auto",
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
    }

    with app.app_context():
        recipe_result = assistant.analyze(recipe_payload)
        recipe_list_result = assistant.analyze(recipe_list_payload)
        bundle_result = assistant.analyze(bundle_payload)
        training_result = assistant.analyze(training_payload)

    assert recipe_result["preview"]["primary_candidate"]["target_type"] == "recipe"
    assert recipe_list_result["preview"]["primary_candidate"]["target_type"] == "recipe_bundle"
    assert bundle_result["preview"]["primary_candidate"]["target_type"] == "recipe_bundle"
    assert training_result["preview"]["primary_candidate"]["target_type"] == "training_plan"
