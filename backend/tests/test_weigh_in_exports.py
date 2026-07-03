import csv
import io
import json

import pytest

from app.extensions import db
from app.models import User, WeighIn
from app.services.exporters import ExportError
from app.services.exporters.weigh_in import (
    WeighInHistoryCsvExporter,
    WeighInJsonExporter,
)
from app.services.validation import validate_json_document
from tests.conftest import login


def _create_manual_weigh_in(client):
    client.post(
        "/manual/weigh-in",
        data={
            "recorded_at": "2026-07-08T06:45",
            "weight_kg": "73.8",
            "body_fat_percent": "17.8",
            "muscle_mass_kg": "58.5",
            "water_percent": "56.8",
            "visceral_fat": "6",
            "bmr_kcal": "1725",
            "bmi": "23.3",
            "notes": "Fictional export weigh-in",
        },
    )


def test_weigh_in_export_services_and_http(app, client, user):
    login(client)
    _create_manual_weigh_in(client)
    with app.app_context():
        record = db.session.execute(db.select(WeighIn)).scalar_one()
        record_id = record.id

        artifact = WeighInJsonExporter().export(record, user)
        document = json.loads(artifact.content)
        validate_json_document(document, "weigh_in")
        assert document["data"]["weight_kg"] == 73.8
        assert document["data"]["water_percent"] == 56.8
        assert document["data"]["bmi"] == 23.3

        csv_artifact = WeighInHistoryCsvExporter().export([record], user)
        rows = list(
            csv.DictReader(io.StringIO(csv_artifact.content.decode("utf-8-sig")))
        )
        assert rows[0]["weight_kg"] == "73.800"
        assert rows[0]["body_fat_percentage"] == "17.800"
        assert csv_artifact.warning is not None

    json_response = client.get(f"/weigh-ins/{record_id}/export/json")
    assert json_response.status_code == 200
    assert json_response.mimetype == "application/json"
    validate_json_document(json.loads(json_response.data), "weigh_in")

    csv_response = client.get("/weigh-ins/export/csv")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    assert b"muscle_mass_kg" in csv_response.data


def test_weigh_in_exports_are_isolated_by_user(app, client, user):
    login(client)
    _create_manual_weigh_in(client)
    with app.app_context():
        record = db.session.execute(db.select(WeighIn)).scalar_one()
        record_id = record.id
        second = User(username="weigh-in-export-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        with pytest.raises(ExportError):
            WeighInJsonExporter().export(record, second_id)
        with pytest.raises(ExportError):
            WeighInHistoryCsvExporter().export([record], second_id)

    client.post("/logout")
    login(client, "weigh-in-export-second", "second-password")
    assert client.get(f"/weigh-ins/{record_id}/export/json").status_code == 404
    empty_csv = client.get("/weigh-ins/export/csv")
    assert empty_csv.status_code == 200
    assert b"73.800" not in empty_csv.data
