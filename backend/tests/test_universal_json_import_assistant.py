"""Tests for universal JSON assisted import preview."""

from app.services.importers.schema_detector import SchemaDetector
from app.services.importers.universal_json_import_assistant import (
    UniversalJsonImportAssistant,
)


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


def test_schema_detector_detects_standard_recipe(app):
    with app.app_context():
        result = SchemaDetector().detect(_standard_recipe_document())

    assert result["mode"] == "standard"
    assert result["detected_type"] == "recipe"
    assert result["schema_name"] == "recipe"
    assert result["confidence"] == 1.0
    assert result["errors"] == []


def test_schema_detector_routes_non_standard_json_to_assistant(app):
    payload = {
        "metadata": {"source": "demo"},
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
            }
        ],
    }

    with app.app_context():
        result = SchemaDetector().detect(payload, requested_type="weigh_in")

    assert result["mode"] == "assistant_required"
    assert result["detected_type"] == "weigh_in"
    assert result["confidence"] == 0.0
    assert result["schema_name"] is None


def test_assistant_returns_standard_mode_for_official_schema(app):
    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(_standard_recipe_document())

    assert result["mode"] == "standard"
    assert result["detected_type"] == "recipe"
    assert result["candidate_domains"] == []
    assert result["preview"]["actions_available"] == ["import_with_standard_importer"]


def test_assistant_detects_weigh_in_batch_and_canonical_water_mapping(app):
    payload = {
        "metadata": {"source": "demo"},
        "perfil": {"name": "Usuario ficticio"},
        "metas": {"weight_goal_kg": 88},
        "reglas_macros_actuales": {"mode": "low_carb"},
        "entrenamiento": {"preference": "stable_exercises"},
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
                "grasa_corporal_pct": 27.3,
                "body_water_percent": 49.8,
                "musculo_kg": 60.19,
                "metabolismo_basal_kcal": 1788,
            }
        ],
    }

    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(
            payload,
            requested_type="weigh_in",
        )

    assert result["mode"] == "assistant_required"
    assert result["source_shape"] == "consolidated_health_source"

    primary = result["preview"]["primary_candidate"]
    assert primary["target_type"] == "weigh_in_batch"
    assert primary["path"] == "registros"
    assert primary["count"] == 1
    assert primary["suggested_mapping"]["body_water_percent"] == "water_percent"
    assert primary["suggested_mapping"]["peso_kg"] == "weight_kg"

    assert {
        "source_field": "body_water_percent",
        "canonical_field": "water_percent",
    } in primary["aliases_used"]


def test_assistant_detects_food_products_from_pantry_payload(app):
    payload = {
        "alacena": [
            {
                "nombre": "Producto demo",
                "marca": "Marca demo",
                "kcal": 380,
                "proteina_g": 85,
                "grasa_g": 2,
                "carbos_netos_g": 0,
                "fibra_g": 0,
                "sodio_mg": 100,
            },
            {
                "nombre": "Producto demo 2",
                "marca": "Marca demo",
                "kcal": 120,
                "proteina_g": 10,
                "grasa_g": 5,
                "carbos_netos_g": 3,
                "fibra_g": 1,
                "sodio_mg": 90,
            },
        ]
    }

    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(payload)

    assert result["mode"] == "assistant_required"

    primary = result["preview"]["primary_candidate"]
    assert primary["target_type"] == "food_products"
    assert primary["path"] == "alacena"
    assert primary["count"] == 2
    assert primary["suggested_mapping"]["nombre"] == "name"
    assert primary["suggested_mapping"]["marca"] == "brand"
    assert primary["suggested_mapping"]["proteina_g"] == "protein_g_per_100g"


def test_assistant_detects_daily_nutrition_payload(app):
    payload = {
        "nutrition": [
            {
                "fecha": "2026-07-05",
                "calorias": 2100,
                "proteina_g": 140,
                "carbos_netos_g": 120,
                "desayuno": [
                    {"nombre": "Fictional item", "kcal": 300}
                ],
            }
        ]
    }

    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(
            payload,
            requested_type="daily_nutrition",
        )

    assert result["mode"] == "assistant_required"
    primary = result["preview"]["primary_candidate"]
    assert primary["target_type"] == "daily_nutrition"
    assert primary["path"] == "nutrition"
    assert primary["suggested_mapping"]["fecha"] == "date"
    assert primary["suggested_mapping"]["calorias"] == "calories"
    assert primary["suggested_mapping"]["desayuno"] == "breakfast"


def test_assistant_detects_training_plan_payload(app):
    payload = {
        "rutinas": [
            {
                "nombre": "Rutina demo",
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
        result = UniversalJsonImportAssistant().analyze(
            payload,
            requested_type="training_plan",
        )

    detected_types = {candidate["target_type"] for candidate in result["candidate_domains"]}
    assert result["mode"] == "assistant_required"
    assert "training_plan" in detected_types

    training_candidate = next(
        candidate
        for candidate in result["candidate_domains"]
        if candidate["target_type"] == "training_plan"
        and "semanas" in candidate["suggested_mapping"]
    )
    assert training_candidate["suggested_mapping"]["nombre"] == "name"
    assert training_candidate["suggested_mapping"]["semanas"] == "weeks"


def test_assistant_detects_recipe_and_recipe_bundle_payloads(app):
    recipe_payload = {
        "receta": {
            "nombre": "Receta demo",
            "ingredientes": [{"producto": "Producto demo", "cantidad_g": 40}],
        }
    }
    bundle_payload = {
        "recetas": [
            {
                "nombre": "Receta demo",
                "ingredientes": [{"producto": "Producto demo", "cantidad_g": 40}],
            }
        ]
    }

    with app.app_context():
        recipe_result = UniversalJsonImportAssistant().analyze(
            recipe_payload,
            requested_type="recipe",
        )
        bundle_result = UniversalJsonImportAssistant().analyze(
            bundle_payload,
            requested_type="recipe_bundle",
        )

    recipe_types = {candidate["target_type"] for candidate in recipe_result["candidate_domains"]}
    bundle_types = {candidate["target_type"] for candidate in bundle_result["candidate_domains"]}

    assert "recipe" in recipe_types
    assert "recipe_bundle" in bundle_types


def test_assistant_detects_multiple_candidate_domains(app):
    payload = {
        "registros": [
            {
                "fecha": "2026-07-05",
                "peso_kg": 87.25,
                "body_water_percent": 49.8,
            }
        ],
        "productos": [
            {
                "nombre": "Producto demo",
                "marca": "Marca demo",
                "kcal": 380,
                "proteina_g": 85,
            }
        ],
    }

    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(payload)

    detected_types = {
        candidate["target_type"]
        for candidate in result["candidate_domains"]
    }

    assert result["mode"] == "assistant_required"
    assert result["source_shape"] == "consolidated_health_source"
    assert "weigh_in_batch" in detected_types
    assert "food_products" in detected_types


def test_assistant_returns_no_candidates_for_unknown_object(app):
    payload = {
        "random": {
            "foo": "bar",
            "baz": 123,
        }
    }

    with app.app_context():
        result = UniversalJsonImportAssistant().analyze(payload)

    assert result["mode"] == "assistant_required"
    assert result["candidate_domains"] == []
    assert result["preview"]["candidate_count"] == 0
    assert result["preview"]["actions_available"] == ["cancel"]
