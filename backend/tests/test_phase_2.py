import hashlib
import json

import pytest

from app.extensions import db
from app.models import UploadedFile
from app.services.manual_json import ManualJsonGenerationError, generate_standard_json
from app.services.validation import JsonSchemaValidationError, validate_json_document
from tests.conftest import login


VALID_DOCUMENTS = {
    "weigh_in": {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": 1,
        "source_type": "manual_generated",
        "data": {"recorded_at": "2026-07-01T07:30:00+00:00", "weight_kg": 75.2},
    },
    "daily_energy": {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": 1,
        "source_type": "device_sync",
        "data": {"date": "2026-07-01", "total_expenditure_kcal": 2400},
    },
    "daily_nutrition": {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": 1,
        "source_type": "manual_generated",
        "data": {
            "date": "2026-07-01",
            "calories_kcal": 2100,
            "protein_g": 140,
            "carbohydrate_g": 220,
            "fat_g": 70,
        },
    },
    "completed_workout": {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": 1,
        "source_type": "manual_generated",
        "data": {
            "training_plan_id": 1,
            "training_plan_version_id": 1,
            "performed_at": "2026-07-01T12:00:00Z",
            "planned_week_number": 1,
            "planned_day_number": 1,
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Example exercise",
                    "sets": [
                        {
                            "set_number": 1,
                            "planned_set_number": 1,
                            "weight_kg": 40,
                            "reps": 8,
                        }
                    ],
                }
            ],
        },
    },
}


@pytest.mark.parametrize(("schema_name", "document"), VALID_DOCUMENTS.items())
def test_base_schemas_accept_minimum_valid_documents(app, schema_name, document):
    with app.app_context():
        validate_json_document(document, schema_name)


def test_weigh_in_schema_checks_values_and_date_format(app):
    invalid = {
        **VALID_DOCUMENTS["weigh_in"],
        "data": {"recorded_at": "not-a-date", "weight_kg": 0},
    }

    with app.app_context(), pytest.raises(JsonSchemaValidationError) as error:
        validate_json_document(invalid, "weigh_in")

    assert "data.recorded_at" in str(error.value)
    assert "data.weight_kg" in str(error.value)


def test_manual_weigh_in_generates_valid_deduplicated_json(app, client, user):
    login(client)
    form_data = {
        "recorded_at": "2026-07-01T07:30",
        "weight_kg": "75.20",
        "body_fat_percent": "18.5",
        "notes": "Fictional test weigh-in",
    }

    response = client.post("/manual/weigh-in", data=form_data, follow_redirects=True)
    assert response.status_code == 200
    assert b"Pesaje guardado" in response.data

    with app.app_context():
        record = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert record.user_id == user
        assert record.source_type == "manual_generated"
        assert record.mime_type == "application/json"
        assert record.storage_path.startswith(f"uploads/generated/user_{user}/")

        generated_path = (
            app.config["GENERATED_UPLOAD_ROOT"]
            / f"user_{user}"
            / record.stored_filename
        )
        generated_bytes = generated_path.read_bytes()
        assert hashlib.sha256(generated_bytes).hexdigest() == record.sha256

        document = json.loads(generated_bytes)
        assert document["user_id"] == user
        assert document["record_type"] == "weigh_in"
        assert document["source_type"] == "manual_generated"
        assert document["data"]["recorded_at"] == "2026-07-01T07:30:00+00:00"
        assert document["data"]["weight_kg"] == 75.2
        validate_json_document(document, "weigh_in")

    duplicate = client.post("/manual/weigh-in", data=form_data, follow_redirects=True)
    assert b"ya estaba registrado" in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(UploadedFile)).scalars().all()) == 1


def test_manual_json_rejects_a_different_owner(app, user):
    document = {**VALID_DOCUMENTS["weigh_in"], "user_id": user}

    with app.app_context(), pytest.raises(ManualJsonGenerationError):
        generate_standard_json(
            document=document,
            schema_name="weigh_in",
            user_id=user + 1,
            original_filename="weigh_in.json",
        )


def test_manual_weigh_in_rejects_non_finite_numbers(app, client, user):
    login(client)
    response = client.post(
        "/manual/weigh-in",
        data={"recorded_at": "2026-07-01T07:30", "weight_kg": "NaN"},
    )

    assert response.status_code == 200
    assert "Ingresa un número finito.".encode() in response.data
    with app.app_context():
        assert db.session.execute(db.select(UploadedFile)).scalar_one_or_none() is None
