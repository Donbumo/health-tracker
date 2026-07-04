from copy import deepcopy

import pytest

from app.services.validation import JsonSchemaValidationError, validate_json_document


def _valid_export() -> dict:
    return {
        "schema_version": "1.0",
        "type": "user_data_export",
        "exported_at": "2026-07-04T12:00:00+00:00",
        "user": {"id": 1, "email": "fictional@example.test", "role": "user"},
        "data": {
            "uploads": [],
            "weigh_ins": [],
            "daily_nutrition": [],
            "daily_energy": [],
            "daily_balances": [],
            "training_plans": [],
            "training_sessions": [],
            "medical_lab_reports": [],
        },
    }


def test_user_data_export_schema_accepts_valid_empty_sections(app):
    with app.app_context():
        validate_json_document(_valid_export(), "user_data_export")


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda document: document.pop("type"), "type"),
        (
            lambda document: document.__setitem__("type", "other_export"),
            "user_data_export",
        ),
        (
            lambda document: document["user"].__setitem__(
                "password_hash", "fictional-forbidden-value"
            ),
            "password_hash",
        ),
    ],
)
def test_user_data_export_schema_rejects_invalid_headers(app, mutation, expected):
    document = deepcopy(_valid_export())
    mutation(document)

    with app.app_context(), pytest.raises(JsonSchemaValidationError) as error:
        validate_json_document(document, "user_data_export")

    assert expected in str(error.value)


def test_user_data_export_schema_allows_future_sections(app):
    document = _valid_export()
    document["data"]["future_section"] = []

    with app.app_context():
        validate_json_document(document, "user_data_export")
