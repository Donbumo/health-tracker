import json
from pathlib import Path

import pytest

from app.services.validation import JsonSchemaValidationError, validate_json_document


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "qa" / "standard-import"

SCHEMA_BY_DOMAIN = {
    "daily_energy": "daily_energy",
    "training_plan": "training_plan",
    "completed_workout": "completed_workout",
    "medical_lab": "medical_lab",
}


def _documents_from_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else [payload]


def _is_intentionally_mixed_or_invalid(path: Path) -> bool:
    return "invalid" in path.name or "batch_mixed" in path.name


def test_standard_import_qa_fixture_package_exists():
    assert FIXTURE_ROOT.is_dir()
    for domain in SCHEMA_BY_DOMAIN:
        assert (FIXTURE_ROOT / domain / "README.md").is_file()


def test_standard_import_qa_valid_fixtures_match_schemas(app):
    with app.app_context():
        for domain, schema_name in SCHEMA_BY_DOMAIN.items():
            for path in sorted((FIXTURE_ROOT / domain).glob("*.json")):
                if _is_intentionally_mixed_or_invalid(path):
                    continue
                for document in _documents_from_file(path):
                    validate_json_document(document, schema_name)


@pytest.mark.parametrize("domain", sorted(SCHEMA_BY_DOMAIN))
def test_standard_import_qa_invalid_fixtures_fail_schema(app, domain):
    schema_name = SCHEMA_BY_DOMAIN[domain]
    invalid_paths = sorted((FIXTURE_ROOT / domain).glob("*invalid*.json"))
    assert invalid_paths, f"{domain} should include invalid fixtures"

    with app.app_context():
        for path in invalid_paths:
            documents = _documents_from_file(path)
            invalid_count = 0
            for document in documents:
                try:
                    validate_json_document(document, schema_name)
                except JsonSchemaValidationError:
                    invalid_count += 1
            assert invalid_count >= 1, f"{path} should include at least one invalid document"
