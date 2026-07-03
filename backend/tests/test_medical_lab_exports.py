import csv
import io
import json

import pytest

from app.extensions import db
from app.models import MedicalLabReport, User
from app.services.exporters import ExportError
from app.services.exporters.medical_lab import (
    MedicalLabCsvExporter,
    MedicalLabJsonExporter,
)
from app.services.validation import validate_json_document
from tests.conftest import login


def _create_report(client):
    return client.post(
        "/medical/labs/manual",
        data={
            "date": "2026-07-03",
            "laboratory_name": "Laboratorio ficticio QA",
            "marker_name": "Marcador exportable ficticio",
            "value": "11.5",
            "unit": "unidad_qa",
            "reference_min": "10",
            "reference_max": "13",
            "status": "normal",
        },
    )


def test_medical_lab_exports_service_and_http(app, client, user):
    login(client)
    _create_report(client)
    with app.app_context():
        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        report_id = report.id
        json_artifact = MedicalLabJsonExporter().export(report, user)
        document = json.loads(json_artifact.content)
        validate_json_document(document, "medical_lab")
        assert document["markers"][0]["value"] == 11.5

        csv_artifact = MedicalLabCsvExporter().export(report, user)
        rows = list(
            csv.DictReader(io.StringIO(csv_artifact.content.decode("utf-8-sig")))
        )
        assert rows[0]["marker_name"] == "Marcador exportable ficticio"
        assert rows[0]["status"] == "normal"

    json_response = client.get(f"/medical/labs/{report_id}/export.json")
    assert json_response.status_code == 200
    assert json_response.mimetype == "application/json"
    csv_response = client.get(f"/medical/labs/{report_id}/export.csv")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    marker_csv = client.get(
        "/medical/markers/Marcador%20exportable%20ficticio/export.csv"
    )
    assert marker_csv.status_code == 200
    assert marker_csv.mimetype == "text/csv"
    assert b"change_previous" in marker_csv.data


def test_medical_lab_exports_are_isolated_by_user(app, client, user):
    login(client)
    _create_report(client)
    with app.app_context():
        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        report_id = report.id
        second = User(username="medical-export-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        with pytest.raises(ExportError):
            MedicalLabJsonExporter().export(report, second_id)
        with pytest.raises(ExportError):
            MedicalLabCsvExporter().export(report, second_id)

    client.post("/logout")
    login(client, "medical-export-second", "second-password")
    assert client.get(f"/medical/labs/{report_id}/export.json").status_code == 404
    assert client.get(f"/medical/labs/{report_id}/export.csv").status_code == 404
    assert client.get(
        "/medical/markers/Marcador%20exportable%20ficticio/export.csv"
    ).status_code == 404
