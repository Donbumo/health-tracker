import json

import pytest

from app.extensions import db
from app.models import ImportRun
from app.services.importers.import_prompt_catalog import ImportPromptCatalog
from app.services.importers.standard_json_generator import SUPPORTED_TARGETS
from app.services.validation import JsonSchemaValidationError, validate_json_document
from tests.conftest import login


EXPECTED_TARGETS = {
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


def _catalog() -> ImportPromptCatalog:
    return ImportPromptCatalog()


def test_import_prompt_catalog_contains_exact_standard_targets(app):
    with app.app_context():
        catalog = _catalog()

        assert set(catalog.target_types()) == EXPECTED_TARGETS
        assert set(catalog.target_types()) == SUPPORTED_TARGETS
        assert set(catalog.as_dict()) == EXPECTED_TARGETS


@pytest.mark.parametrize("target_type", sorted(EXPECTED_TARGETS))
def test_import_prompt_catalog_prompt_is_safe_and_json_only(app, target_type):
    with app.app_context():
        entry = _catalog().get(target_type)

    prompt = entry["prompt"]
    serialized_entry = json.dumps(entry, ensure_ascii=False)

    assert "solo JSON" in prompt
    assert "```json" not in prompt
    assert "Health Tracker no envía tus datos a ninguna IA" in prompt
    assert "test-user" not in serialized_entry
    assert "demo@example.com" not in serialized_entry
    assert '"user_id": 1' not in prompt
    assert '"user_id": 0' not in prompt
    assert "password" not in prompt.lower()
    assert entry["target_type"] == target_type
    assert entry["schema_name"]
    assert entry["required"]


@pytest.mark.parametrize("target_type", sorted(EXPECTED_TARGETS))
def test_import_prompt_catalog_required_and_type_match_schema(app, target_type):
    with app.app_context():
        entry = _catalog().get(target_type)

    template = entry["template"]
    if "record_type" in template:
        assert template["record_type"] in {target_type, entry["schema_name"]}
    if "type" in template:
        assert template["type"] in {target_type, entry["schema_name"]}
    assert "schema_version" in template
    for required_path in entry["required"]:
        root_key = required_path.split(".", maxsplit=1)[0].replace("[]", "")
        assert root_key in template or root_key in {"markers", "ingredients", "recipes"}


def test_import_prompt_catalog_templates_validate_when_no_placeholders(app):
    expected_valid = {"food_products", "recipe", "recipe_bundle"}
    with app.app_context():
        catalog = _catalog()
        for target_type in sorted(EXPECTED_TARGETS):
            entry = catalog.get(target_type)
            template_json = entry["template_json"]
            assert "REEMPLAZAR_USER_ID" not in template_json or target_type not in expected_valid

            if target_type in expected_valid:
                validate_json_document(entry["template"], entry["schema_name"])
            else:
                with pytest.raises(JsonSchemaValidationError):
                    validate_json_document(entry["template"], entry["schema_name"])


def test_import_prompt_catalog_id_markers_only_where_references_need_them(app):
    with app.app_context():
        catalog = _catalog()

        completed = catalog.get("completed_workout")["template_json"]
        nutrition = catalog.get("daily_nutrition")["template_json"]
        recipe = catalog.get("recipe")["template_json"]

    assert "REEMPLAZAR_PLAN_ID" in completed
    assert "REEMPLAZAR_PLAN_VERSION_ID" in completed
    assert "REEMPLAZAR_PLAN_ID" not in nutrition
    assert "REEMPLAZAR_PLAN_ID" not in recipe


def test_standard_import_prompt_endpoint_requires_login(client):
    response = client.get("/imports/standard/prompts/daily_energy")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_standard_import_prompt_endpoint_returns_safe_json(app, client, user):
    login(client)
    response = client.get("/imports/standard/prompts/daily_energy")

    assert response.status_code == 200
    payload = response.get_json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["target_type"] == "daily_energy"
    assert payload["schema_name"] == "daily_energy"
    assert "solo JSON" in payload["prompt"]
    assert "test-user" not in serialized
    assert "password" not in serialized.lower()
    with app.app_context():
        assert db.session.execute(db.select(ImportRun)).scalars().all() == []


def test_standard_import_prompt_endpoint_rejects_unknown_target(client, user):
    login(client)
    response = client.get("/imports/standard/prompts/not-a-target")

    assert response.status_code == 404


def test_standard_import_page_renders_ai_prompt_helper_without_user_payload(app, client, user):
    login(client)
    response = client.get("/imports/standard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Preparar archivo con IA" in html
    assert 'id="ai-prompt-target"' in html
    assert 'id="ai-prompt-text"' in html
    assert 'id="ai-template-json"' in html
    assert "Copiar prompt" in html
    assert "Copiar plantilla JSON" in html
    assert "Health Tracker no envía tus datos a ninguna IA" in html
    assert "Detectar autom" in html
    assert "mobile-menu" in html
    assert "test-user" not in html.split("Prompt base listo para copiar", maxsplit=1)[-1]
    with app.app_context():
        assert db.session.execute(db.select(ImportRun)).scalars().all() == []


def test_standard_import_page_preselects_prompt_target_from_query(client, user):
    login(client)
    response = client.get("/imports/standard?target=medical_lab")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<option value="medical_lab" selected>' in html
    assert "medical_lab.schema.json" in html
