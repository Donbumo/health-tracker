from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import io
import importlib.util
import json
from pathlib import Path
from threading import Barrier
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker

from app import create_app
from app.api_v1.rate_limit import rate_limiter
from app.extensions import db
from app.models import (
    LabResult,
    LabResultRevision,
    MedicalAuditEvent,
    MedicalDocument,
    MedicalDuplicateCandidate,
    MedicalStudy,
    User,
)
from tests.test_mobile_sync import _api_login, _auth


@pytest.fixture(autouse=True)
def clear_rate_limits():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _headers(token, key=None):
    value = _auth(token)
    if key:
        value["Idempotency-Key"] = key
    return value


def _study_payload(public_id="a1000000-0000-4000-8000-000000000001", **changes):
    value = {
        "public_id": public_id,
        "study_type": "laboratory",
        "title": "Panel ficticio QA",
        "laboratory_name": "Laboratorio Demo Norte",
        "professional_name": "Profesional Ficticio",
        "study_date": "2026-07-01",
        "issued_date": "2026-07-02",
        "timezone": "America/Mexico_City",
        "notes": "Datos completamente ficticios para QA.",
        "state": "complete",
        "source": "mobile",
    }
    value.update(changes)
    return value


def _result_payload(public_id=None, **changes):
    value = {
        "public_id": public_id or str(uuid.uuid4()),
        "panel_name": "Química ficticia",
        "display_name": "Glucosa QA",
        "canonical_key": "glucose",
        "value_type": "numeric",
        "original_value": "91.25",
        "numeric_value": "91.25",
        "comparator": "equal",
        "original_unit": "mg/L",
        "reference_lower": "80",
        "reference_upper": "100",
        "reference_text": "80 a 100 (rango ficticio del informe QA)",
        "source_status": "within_range",
        "method": "Método QA-A",
        "specimen": "Muestra ficticia",
        "notes": "Resultado ficticio.",
        "source": "mobile",
    }
    value.update(changes)
    return value


def _create(client, token, payload=None, key="study-create"):
    return client.post(
        "/api/v1/mobile/medical-studies",
        json=payload or _study_payload(),
        headers=_headers(token, key),
    )


def _second_token(app, client):
    with app.app_context():
        account = User(username="medical-other", role="user")
        account.set_password("fictional-password")
        db.session.add(account)
        db.session.commit()
    return _api_login(
        client,
        username="medical-other",
        password="fictional-password",
        device_id="a9000000-0000-4000-8000-000000000001",
    )["access_token"]


def test_empty_create_patch_archive_owner_revision_and_idempotency(app, client, user):
    token = _api_login(client)["access_token"]
    empty = client.get("/api/v1/mobile/medical-studies", headers=_headers(token))
    assert empty.status_code == 200 and empty.get_json()["data"]["items"] == []

    first = _create(client, token)
    replay = _create(client, token)
    assert first.status_code == replay.status_code == 201
    study = first.get_json()["data"]
    assert study["revision"] == 1 and study["panel_count"] == 0
    assert replay.get_json()["data"] == study

    stale = client.patch(
        f"/api/v1/mobile/medical-studies/{study['public_id']}",
        json={"base_revision": 0, "title": "Cambio QA"},
        headers=_headers(token, "study-stale"),
    )
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "revision_conflict"
    changed = client.patch(
        f"/api/v1/mobile/medical-studies/{study['public_id']}",
        json={"base_revision": 1, "title": "Cambio ficticio QA"},
        headers=_headers(token, "study-patch"),
    ).get_json()["data"]
    assert changed["revision"] == 2 and changed["title"] == "Cambio ficticio QA"

    other = _second_token(app, client)
    assert client.get(
        f"/api/v1/mobile/medical-studies/{study['public_id']}", headers=_headers(other)
    ).status_code == 404
    archived = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/archive",
        json={"base_revision": 2}, headers=_headers(token, "study-archive"),
    ).get_json()["data"]
    assert archived["state"] == "archived" and archived["revision"] == 3


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"study_type": "diagnosis"}, "invalid_study_type"),
        ({"issued_date": "2026-06-01"}, "invalid_date_range"),
        ({"timezone": "Mars/Olympus"}, "invalid_timezone"),
        ({"extra": "x"}, "invalid_request"),
    ],
)
def test_study_validation(client, user, changes, code):
    token = _api_login(client)["access_token"]
    response = _create(client, token, _study_payload(**changes), f"invalid-study-{code}")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code


@pytest.mark.parametrize(
    "payload,expected_type",
    [
        (_result_payload(), "numeric"),
        (_result_payload(value_type="text", original_value="Comentario QA", numeric_value=None, original_unit=None, reference_lower=None, reference_upper=None), "text"),
        (_result_payload(value_type="positive_negative", original_value="Negativo QA", numeric_value=None, original_unit=None, reference_lower=None, reference_upper=None, source_status="not_provided"), "positive_negative"),
        (_result_payload(value_type="detected_not_detected", original_value="No detectado QA", numeric_value=None, original_unit=None, reference_lower=None, reference_upper=None), "detected_not_detected"),
    ],
)
def test_numeric_text_and_qualitative_results(client, user, payload, expected_type):
    token = _api_login(client)["access_token"]
    study = _create(client, token).get_json()["data"]
    response = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/results",
        json=payload,
        headers=_headers(token, f"result-{expected_type}"),
    )
    assert response.status_code == 201
    result = response.get_json()["data"]
    assert result["value_type"] == expected_type
    assert result["original_value"] == payload["original_value"]
    assert result["range_notice"] == "Según el rango incluido en este informe."
    if expected_type == "numeric":
        assert result["numeric_value"] == "91.25"
        assert result["derived_range_status"] == "within_reported_range"
        assert result["original_unit"] == "mg/L" and result["canonical_unit"] == "mg/L"
    else:
        assert result["numeric_value"] is None
        assert result["derived_range_status"] == "not_computable"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"numeric_value": "NaN"}, "invalid_number"),
        ({"numeric_value": "Infinity"}, "invalid_number"),
        ({"reference_lower": "101", "reference_upper": "100"}, "invalid_range"),
        ({"comparator": "about"}, "invalid_comparator"),
        ({"source_status": "dangerous"}, "invalid_source_status"),
        ({"canonical_key": "Ambiguous Key"}, "invalid_marker"),
    ],
)
def test_result_validation(client, user, changes, code):
    token = _api_login(client)["access_token"]
    study = _create(client, token).get_json()["data"]
    response = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/results",
        json=_result_payload(**changes), headers=_headers(token, f"invalid-result-{code}"),
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code


def test_result_correction_revision_history_delete_and_cross_access(app, client, user):
    token = _api_login(client)["access_token"]
    study = _create(client, token).get_json()["data"]
    result = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/results",
        json=_result_payload(), headers=_headers(token, "result-create"),
    ).get_json()["data"]
    assert result["revision"] == 1 and len(result["revisions"]) == 1
    corrected = client.patch(
        f"/api/v1/mobile/lab-results/{result['public_id']}",
        json={"base_revision": 1, "original_value": "92", "numeric_value": "92", "correction_reason": "Corrección QA"},
        headers=_headers(token, "result-correct"),
    ).get_json()["data"]
    assert corrected["revision"] == 2 and len(corrected["revisions"]) == 2
    assert corrected["revisions"][-1]["correction_reason"] == "Corrección QA"
    other = _second_token(app, client)
    assert client.patch(
        f"/api/v1/mobile/lab-results/{result['public_id']}",
        json={"base_revision": 2, "notes": "No autorizado"},
        headers=_headers(other, "cross-result"),
    ).status_code == 404
    deleted = client.delete(
        f"/api/v1/mobile/lab-results/{result['public_id']}",
        json={"base_revision": 2}, headers=_headers(token, "result-delete"),
    )
    assert deleted.status_code == 200 and deleted.get_json()["data"]["deleted"] is True


def test_marker_catalog_history_compatible_and_incompatible(client, user):
    token = _api_login(client)["access_token"]
    catalog = client.get("/api/v1/mobile/lab-markers?q=gluc", headers=_headers(token)).get_json()["data"]
    assert catalog["clinical_ranges_included"] is False
    assert catalog["items"][0]["canonical_key"] == "glucose"
    assert not catalog["items"][0]["observed_units"]

    first = _create(client, token).get_json()["data"]
    client.post(f"/api/v1/mobile/medical-studies/{first['public_id']}/results", json=_result_payload(), headers=_headers(token, "history-one"))
    second_payload = _study_payload("a1000000-0000-4000-8000-000000000002", study_date="2026-07-15", issued_date="2026-07-16")
    second = _create(client, token, second_payload, "study-two").get_json()["data"]
    client.post(f"/api/v1/mobile/medical-studies/{second['public_id']}/results", json=_result_payload(original_value="0.095", numeric_value="0.095", original_unit="g/L"), headers=_headers(token, "history-two"))
    history = client.get("/api/v1/mobile/lab-history/glucose?period=all", headers=_headers(token)).get_json()["data"]
    assert history["count"] == 2 and history["series_comparable"] is True
    assert history["points"][1]["normalized_value"] == "95"
    assert history["points"][1]["absolute_change"] == "3.75"

    third_payload = _study_payload("a1000000-0000-4000-8000-000000000003", study_date="2026-07-20", issued_date="2026-07-21")
    third = _create(client, token, third_payload, "study-three").get_json()["data"]
    client.post(f"/api/v1/mobile/medical-studies/{third['public_id']}/results", json=_result_payload(original_value="5", numeric_value="5", original_unit="mmol/L", method="Método QA-B"), headers=_headers(token, "history-three"))
    incompatible = client.get("/api/v1/mobile/lab-history/glucose", headers=_headers(token)).get_json()["data"]
    assert incompatible["series_comparable"] is False
    assert incompatible["comparison_notice"] == "Unidades o métodos no comparables"


@pytest.mark.parametrize(
    "filename,mime,content",
    [
        ("informe-ficticio.pdf", "application/pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF"),
        ("imagen-ficticia.jpg", "image/jpeg", b"\xff\xd8\xff\xe0QA-FICTIONAL\xff\xd9"),
        ("captura-ficticia.png", "image/png", b"\x89PNG\r\n\x1a\nQA-FICTIONAL"),
    ],
)
def test_safe_document_upload_download_duplicate_and_delete(client, user, filename, mime, content):
    token = _api_login(client)["access_token"]
    study = _create(client, token).get_json()["data"]
    response = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/documents",
        data={"file": (io.BytesIO(content), filename, mime)},
        headers=_headers(token, f"document-{mime}"), content_type="multipart/form-data",
    )
    assert response.status_code == 201
    document = response.get_json()["data"]
    assert document["sha256"] == hashlib.sha256(content).hexdigest()
    download = client.get(f"/api/v1/mobile/medical-documents/{document['public_id']}/download", headers=_headers(token))
    assert download.status_code == 200 and download.data == content
    assert "no-store" in download.headers["Cache-Control"]
    duplicate = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/documents",
        data={"file": (io.BytesIO(content), filename, mime)},
        headers=_headers(token, f"document-duplicate-{mime}"), content_type="multipart/form-data",
    )
    assert duplicate.status_code == 200 and duplicate.get_json()["data"]["duplicate"] is True
    deleted = client.delete(
        f"/api/v1/mobile/medical-documents/{document['public_id']}",
        json={"base_revision": 1, "confirmed": True}, headers=_headers(token, f"document-delete-{mime}"),
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/mobile/medical-documents/{document['public_id']}", headers=_headers(token)).status_code == 404


@pytest.mark.parametrize(
    "filename,mime,content,code",
    [
        ("falso.pdf", "application/pdf", b"<html>active</html>", "active_content_rejected"),
        ("falso.png", "image/png", b"%PDF-1.4\n%%EOF", "mime_mismatch"),
        ("cifrado.pdf", "application/pdf", b"%PDF-1.4\n/Encrypt true\n%%EOF", "encrypted_document"),
        ("script.svg", "image/svg+xml", b"<svg><script>x</script></svg>", "active_content_rejected"),
    ],
)
def test_document_rejections(client, user, filename, mime, content, code):
    token = _api_login(client)["access_token"]
    study = _create(client, token).get_json()["data"]
    response = client.post(
        f"/api/v1/mobile/medical-studies/{study['public_id']}/documents",
        data={"file": (io.BytesIO(content), filename, mime)},
        headers=_headers(token, f"reject-{code}"), content_type="multipart/form-data",
    )
    assert response.status_code in {400, 415}
    assert response.get_json()["error"]["code"] == code


def _medical_document():
    return {
        "format": "health-tracker-medical-lab-v1",
        "schema_version": "1.0",
        "study": {
            "public_id": "b1000000-0000-4000-8000-000000000001",
            "study_type": "laboratory",
            "title": "Import ficticio QA",
            "laboratory_name": "Laboratorio Ficticio Sur",
            "professional_name": None,
            "study_date": "2026-06-01",
            "issued_date": None,
            "timezone": "UTC",
            "notes": None,
            "state": "complete",
            "source": "json_import",
            "revision": 1,
        },
        "panels": [{
            "public_id": "b2000000-0000-4000-8000-000000000001",
            "name": "Panel QA",
            "display_order": 0,
            "source": "json_import",
            "revision": 1,
            "results": [{
                "public_id": "b3000000-0000-4000-8000-000000000001",
                "display_name": "Marcador Ficticio",
                "canonical_key": None,
                "value_type": "text",
                "original_value": "Texto QA",
                "numeric_value": None,
                "comparator": "none",
                "original_unit": None,
                "reference_lower": None,
                "reference_upper": None,
                "reference_text": "Referencia textual ficticia",
                "source_status": "not_provided",
                "method": None,
                "specimen": None,
                "notes": None,
                "display_order": 0,
                "source": "json_import",
                "revision": 1,
            }],
        }],
        "attachments": [],
    }


def test_json_preview_read_only_confirm_idempotent_and_duplicate(client, app, user):
    token = _api_login(client)["access_token"]
    document = _medical_document()
    preview = client.post(
        "/api/v1/mobile/medical-imports/preview",
        data={"file": (io.BytesIO(json.dumps(document).encode()), "medical-qa.json", "application/json")},
        headers=_headers(token), content_type="multipart/form-data",
    )
    assert preview.status_code == 200
    value = preview.get_json()["data"]
    assert value["valid"] is True and value["read_only"] is True
    with app.app_context():
        assert db.session.execute(db.select(MedicalStudy)).scalar_one_or_none() is None
    payload = {"document": value["document"], "confirmation_token": value["confirmation_token"], "confirmed": True}
    applied = client.post("/api/v1/mobile/medical-imports/confirm", json=payload, headers=_headers(token, "json-confirm"))
    replay = client.post("/api/v1/mobile/medical-imports/confirm", json=payload, headers=_headers(token, "json-confirm"))
    assert applied.status_code == replay.status_code == 200
    assert applied.get_json()["data"] == replay.get_json()["data"]

    again = client.post(
        "/api/v1/mobile/medical-imports/preview",
        data={"file": (io.BytesIO(json.dumps(document).encode()), "medical-qa.json", "application/json")},
        headers=_headers(token), content_type="multipart/form-data",
    ).get_json()["data"]
    assert again["duplicate_count"] == 1 and again["new_count"] == 0
    second_payload = {"document": again["document"], "confirmation_token": again["confirmation_token"], "confirmed": True}
    second = client.post("/api/v1/mobile/medical-imports/confirm", json=second_payload, headers=_headers(token, "json-confirm-two"))
    assert second.get_json()["data"]["created"] == 0 and second.get_json()["data"]["skipped"] == 1


def test_csv_preview_valid_formula_rejected_unknown_columns_and_template(client, user):
    token = _api_login(client)["access_token"]
    template = client.get("/api/v1/mobile/medical-imports/template.csv", headers=_headers(token))
    assert template.status_code == 200 and template.data.startswith(b"format,schema_version,")
    header = template.data.decode().strip()
    values = [
        "health-tracker-medical-lab-v1", "1.0", "", "laboratory", "CSV ficticio QA",
        "Laboratorio Demo CSV", "", "2026-05-01", "", "UTC", "", "complete",
        "", "Panel CSV QA", "0", "", "Marcador CSV QA", "", "numeric", "-1.5", "-1.5",
        "equal", "mg/L", "-2", "2", "Rango ficticio CSV", "within_range", "", "", "", "0",
    ]
    buffer = io.StringIO(newline="")
    writer = __import__("csv").writer(buffer, lineterminator="\n")
    writer.writerow(header.split(",")); writer.writerow(values)
    valid = client.post(
        "/api/v1/mobile/medical-imports/preview",
        data={"file": (io.BytesIO(buffer.getvalue().encode()), "qa.csv", "text/csv")},
        headers=_headers(token), content_type="multipart/form-data",
    ).get_json()["data"]
    assert valid["valid"] is True and valid["row_count"] == 1

    values[4] = "=HYPERLINK(\"bad\")"
    buffer = io.StringIO(newline=""); writer = __import__("csv").writer(buffer, lineterminator="\n")
    writer.writerow(header.split(",")); writer.writerow(values)
    rejected = client.post(
        "/api/v1/mobile/medical-imports/preview",
        data={"file": (io.BytesIO(buffer.getvalue().encode()), "qa.csv", "text/csv")},
        headers=_headers(token), content_type="multipart/form-data",
    ).get_json()["data"]
    assert rejected["valid"] is False
    assert any(item["code"] == "formula_rejected" for item in rejected["errors"])

    bad_header = header + ",unknown_column\n"
    unknown = client.post(
        "/api/v1/mobile/medical-imports/preview",
        data={"file": (io.BytesIO(bad_header.encode()), "qa.csv", "text/csv")},
        headers=_headers(token), content_type="multipart/form-data",
    ).get_json()["data"]
    assert unknown["valid"] is False and unknown["errors"][0]["code"] == "invalid_headers"


def test_structured_duplicate_candidate_audit_and_permanent_delete(client, app, user):
    token = _api_login(client)["access_token"]
    first = _create(client, token).get_json()["data"]
    client.post(f"/api/v1/mobile/medical-studies/{first['public_id']}/results", json=_result_payload(), headers=_headers(token, "dupe-result-one"))
    second = _create(client, token, _study_payload("a1000000-0000-4000-8000-000000000009"), "dupe-study-two").get_json()["data"]
    client.post(f"/api/v1/mobile/medical-studies/{second['public_id']}/results", json=_result_payload(public_id="a3000000-0000-4000-8000-000000000009"), headers=_headers(token, "dupe-result-two"))
    detail = client.get(f"/api/v1/mobile/medical-studies/{second['public_id']}", headers=_headers(token)).get_json()["data"]
    assert detail["duplicates"][0]["classification"] == "exact_structured_duplicate"
    with app.app_context():
        assert db.session.execute(db.select(MedicalDuplicateCandidate)).scalar_one()
        audit = db.session.execute(db.select(MedicalAuditEvent)).scalars().all()
        assert audit and all("value" not in (item.details_json or {}) for item in audit)
    refused = client.delete(
        f"/api/v1/mobile/medical-studies/{second['public_id']}",
        json={"base_revision": detail["revision"], "confirmed": True},
        headers=_headers(token, "delete-refused"),
    )
    assert refused.status_code == 400 and refused.get_json()["error"]["code"] == "confirmation_required"
    deleted = client.delete(
        f"/api/v1/mobile/medical-studies/{second['public_id']}",
        json={"base_revision": detail["revision"], "confirmed": True, "impact_acknowledged": True},
        headers=_headers(token, "delete-confirmed"),
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/mobile/medical-studies/{second['public_id']}", headers=_headers(token)).status_code == 404


@pytest.mark.skipif(
    not Path("/.dockerenv").exists(),
    reason="MariaDB medical concurrency contract runs only in the Docker suite",
)
def test_mariadb_medical_idempotency_and_revision_races(app, tmp_path):
    username = f"medical-race-{uuid.uuid4().hex}"
    concurrent_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "medical-race-secret-key-long-enough",
        "API_TOKEN_SIGNING_KEY": "medical-race-api-key-long-enough",
        "DATA_ROOT": tmp_path / "mariadb-medical",
        "UPLOAD_ROOT": tmp_path / "mariadb-medical" / "uploads" / "raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "mariadb-medical" / "uploads" / "generated",
        "PORTABILITY_ROOT": tmp_path / "mariadb-medical" / "portability",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC",
        "WTF_CSRF_ENABLED": False,
        "API_RATE_LIMIT_ENABLED": False,
    })
    with concurrent_app.app_context():
        account = User(username=username, email=f"{username}@example.invalid", role="user")
        account.set_password("fictional-race-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
    try:
        token = _api_login(
            concurrent_app.test_client(), username=f"{username}@example.invalid",
            password="fictional-race-password", device_id="a9111111-1111-4111-8111-111111111111",
        )["access_token"]
        public_id = str(uuid.uuid4())
        create_barrier = Barrier(2)

        def create_once():
            with concurrent_app.test_client() as race_client:
                create_barrier.wait(timeout=10)
                response = _create(
                    race_client, token, _study_payload(public_id), "medical-concurrent-create",
                )
                return response.status_code, response.get_json()["data"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            creates = list(pool.map(lambda _index: create_once(), range(2)))
        assert [status for status, _data in creates] == [201, 201]
        assert {data["public_id"] for _status, data in creates} == {public_id}
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(MedicalStudy).where(
                MedicalStudy.user_id == user_id,
            )) == 1

        patch_barrier = Barrier(2)

        def patch_once(title, key):
            with concurrent_app.test_client() as race_client:
                patch_barrier.wait(timeout=10)
                response = race_client.patch(
                    f"/api/v1/mobile/medical-studies/{public_id}",
                    json={"base_revision": 1, "title": title}, headers=_headers(token, key),
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            patches = list(pool.map(
                lambda values: patch_once(*values),
                [("Cambio ficticio A", "medical-race-patch-a"), ("Cambio ficticio B", "medical-race-patch-b")],
            ))
        assert sorted(patches) == [200, 409]
    finally:
        with concurrent_app.app_context():
            account = db.session.get(User, user_id)
            if account is not None:
                db.session.delete(account)
            db.session.commit()


def test_public_medical_schemas_are_valid_and_no_universal_ranges():
    root = Path(__file__).resolve().parents[2] / "schemas"
    names = [
        "medical_study.schema.json", "medical_lab_panel.schema.json",
        "medical_lab_result.schema.json", "medical_attachment_metadata.schema.json",
        "medical_import_preview.schema.json", "medical_import_result.schema.json",
    ]
    for name in names:
        schema = json.loads((root / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert "healthy" not in json.dumps(schema).casefold()
        assert "diagnosis" not in json.dumps(schema).casefold()
    document = _medical_document()
    validator = Draft202012Validator(json.loads((root / "medical_study.schema.json").read_text()), format_checker=FormatChecker())
    assert list(validator.iter_errors(document)) == []


def test_medical_migration_0035_is_additive_reversible_and_reupgradeable(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260731_0035_medical_records.py"
    spec = importlib.util.spec_from_file_location("medical_records_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20260731_0034"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'medical-migration.db'}")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("uploaded_files", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    metadata.create_all(engine)
    expected = {
        "medical_studies", "medical_study_sources", "lab_panels", "lab_results",
        "lab_result_revisions", "medical_documents", "medical_duplicate_candidates",
        "medical_audit_events",
    }
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    assert expected <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        connection.execute(sa.text(
            "INSERT INTO medical_studies "
            "(public_id,user_id,study_type,title,study_date,state,source,revision) VALUES "
            "('79999999-9999-4999-8999-999999999991',1,'laboratory','Estudio QA','2026-07-01','complete','manual',1)"
        ))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO medical_studies "
                "(public_id,user_id,study_type,title,study_date,state,source,revision) VALUES "
                "('79999999-9999-4999-8999-999999999992',1,'diagnosis','Inválido QA','2026-07-01','complete','manual',1)"
            ))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    assert expected.isdisjoint(sa.inspect(engine).get_table_names())
    assert {"users", "uploaded_files"} <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    assert expected <= set(sa.inspect(engine).get_table_names())
    engine.dispose()
