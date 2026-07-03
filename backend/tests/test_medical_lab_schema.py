import pytest

from app.services.validation import JsonSchemaValidationError, validate_json_document


def medical_lab_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "type": "medical_lab",
        "user_id": user_id,
        "source_type": "uploaded",
        "date": "2026-07-03",
        "laboratory_name": "Laboratorio ficticio QA",
        "doctor_name": "Profesional ficticio QA",
        "source": "qa_fixture",
        "notes": "Reporte completamente ficticio.",
        "markers": [
            {
                "name": "Marcador numérico ficticio",
                "code": "QA-NUM",
                "value": 12.5,
                "unit": "unidad_qa",
                "reference_min": 10,
                "reference_max": 15,
                "status": "normal",
            },
            {
                "name": "Marcador textual ficticio",
                "value": "no reactivo ficticio",
                "unit": "cualitativo",
                "reference_text": "no reactivo",
                "status": "unknown",
            },
        ],
    }


def test_medical_lab_schema_accepts_numeric_textual_and_optional_values(app, user):
    with app.app_context():
        validate_json_document(medical_lab_document(user), "medical_lab")


def test_medical_lab_schema_requires_at_least_one_marker(app, user):
    document = medical_lab_document(user)
    document["markers"] = []

    with app.app_context(), pytest.raises(JsonSchemaValidationError) as error:
        validate_json_document(document, "medical_lab")

    assert "markers" in str(error.value)


def test_medical_lab_schema_rejects_invalid_status_and_blank_unit(app, user):
    document = medical_lab_document(user)
    document["markers"][0]["status"] = "critical"
    document["markers"][0]["unit"] = ""

    with app.app_context(), pytest.raises(JsonSchemaValidationError) as error:
        validate_json_document(document, "medical_lab")

    assert "markers.0.status" in str(error.value)
    assert "markers.0.unit" in str(error.value)
