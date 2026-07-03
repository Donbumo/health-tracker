import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import MedicalLabReport, UploadedFile, User
from tests.conftest import login
from tests.test_medical_lab_schema import medical_lab_document


def _upload(client, document: dict, filename: str = "medical-lab.json"):
    return client.post(
        "/medical/labs/import",
        data={"file": (io.BytesIO(json.dumps(document).encode()), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_medical_lab_list_import_and_detail(app, client, user):
    login(client)
    empty = client.get("/medical/labs")
    assert empty.status_code == 200
    assert b"Sin estudios registrados" in empty.data
    assert b"Capturar nuevo" in empty.data

    response = _upload(client, medical_lab_document(user))
    assert response.status_code == 200
    assert b"Reporte m" in response.data
    assert b"Marcador num" in response.data
    with app.app_context():
        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        report_id = report.id
        assert report.user_id == user
        assert len(report.results) == 2
    assert client.get(f"/medical/labs/{report_id}").status_code == 200


def test_medical_lab_import_error_and_duplicate_are_clear(app, client, user):
    login(client)
    document = medical_lab_document(user)
    assert _upload(client, document).status_code == 200
    duplicate = _upload(client, document, "duplicate.json")
    assert b"ya hab" in duplicate.data

    invalid = medical_lab_document(user)
    invalid["markers"] = []
    rejected = _upload(client, invalid, "invalid.json")
    assert rejected.status_code == 200
    assert b"No fue posible importar" in rejected.data
    with app.app_context():
        source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.import_status == "error")
        ).scalar_one()
        assert "markers" in source.error_message


def test_manual_medical_lab_creates_generated_json_and_numeric_result(
    app,
    client,
    user,
):
    login(client)
    response = client.post(
        "/medical/labs/manual",
        data={
            "date": "2026-07-03",
            "laboratory_name": "Laboratorio ficticio QA",
            "marker_name": "Marcador manual ficticio",
            "value": "7.25",
            "unit": "unidad_qa",
            "reference_min": "5",
            "reference_max": "9",
            "status": "normal",
            "notes": "Reporte ficticio.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Marcador manual ficticio" in response.data
    with app.app_context():
        report = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        source = db.session.get(UploadedFile, report.source_file_id)
        assert report.results[0].value == Decimal("7.250000")
        assert source.source_type == "manual_generated"
        assert source.detected_type == "medical_lab"
        assert source.import_status == "imported"


def test_medical_lab_routes_are_isolated_by_user(app, client, user):
    login(client)
    _upload(client, medical_lab_document(user))
    with app.app_context():
        report_id = db.session.execute(db.select(MedicalLabReport.id)).scalar_one()
        second = User(username="medical-web-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "medical-web-second", "second-password")
    assert client.get(f"/medical/labs/{report_id}").status_code == 404
    listing = client.get("/medical/labs")
    assert b"Laboratorio ficticio QA" not in listing.data
