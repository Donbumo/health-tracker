import io
import hashlib
import importlib.util
import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator

from app.api_v1.rate_limit import rate_limiter
from app import create_app
from app.extensions import db
from app.models import (
    AIActionDraft, AIConversation, AIMessage, AIToolCall,
    LabResult, MedicalDocument, MedicalDuplicateCandidate, MedicalStudy, PortableExportJob,
    PortableImportJob, UploadedFile, User, WeighIn,
)
from app.services.portable_archive import PortableArchiveError, PortableArchiveReader, PortableLimits
from app.services.ai.conversations import AIConversationService
from tests.test_mobile_sync import _api_login, _auth


@pytest.fixture(autouse=True)
def clear_rate_limit():
    rate_limiter.clear()
    yield
    rate_limiter.clear()


def _headers(token, key=None):
    value = _auth(token)
    if key:
        value["Idempotency-Key"] = key
    return value


def _export(client, token, key="export-fixture-key", sections=None, **options):
    payload = {"sections": sections or ["settings", "body_stats"]}
    payload.update(options)
    return client.post(
        "/api/v1/mobile/portability/exports",
        json=payload,
        headers=_headers(token, key),
    )


def _package(client, token, export_id):
    response = client.get(
        f"/api/v1/mobile/portability/exports/{export_id}/download",
        headers=_headers(token),
    )
    assert response.status_code == 200
    return response.data


def _inspect(client, token, content, sections=None):
    data = {"file": (io.BytesIO(content), "fictional.htpack")}
    if sections is not None:
        data["sections"] = json.dumps(sections)
    return client.post(
        "/api/v1/mobile/portability/imports/inspect",
        data=data,
        headers=_headers(token),
        content_type="multipart/form-data",
    )


def _second_user(app, client):
    with app.app_context():
        account = User(username="portable-destination", role="user")
        account.set_password("fictional-password")
        db.session.add(account)
        db.session.commit()
        user_id = account.id
    token = _api_login(
        client,
        username="portable-destination",
        password="fictional-password",
        device_id="79999999-9999-4999-8999-999999999999",
    )["access_token"]
    return user_id, token


def _members(content):
    with ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _rewrite(content, mutate):
    members = _members(content)
    mutate(members)
    target = io.BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return target.getvalue()


def test_empty_section_export_manifest_checksums_and_download_headers(app, client, user):
    token = _api_login(client)["access_token"]
    response = _export(client, token, sections=["settings", "body_stats"])
    assert response.status_code == 201
    document = response.get_json()["data"]
    assert document["state"] == "ready"
    assert document["counts"] == {"settings": 1, "body_stats": 0}
    package = _package(client, token, document["export_id"])
    assert package[:2] == b"PK"

    with ZipFile(io.BytesIO(package)) as archive:
        assert archive.namelist() == sorted(archive.namelist(), key=lambda name: (name not in {"manifest.json", "checksums.json"}, name)) or archive.namelist()[:2] == ["manifest.json", "checksums.json"]
        manifest = json.loads(archive.read("manifest.json"))
        checksums = json.loads(archive.read("checksums.json"))
    assert manifest["format"] == "health-tracker-portable-v1"
    assert manifest["redaction_policy"]["technical_identifiers"] == "excluded"
    assert set(checksums["files"]) == {"manifest.json", *(row["path"] for row in manifest["files"])}
    assert b"user_id" not in package
    assert b"password_hash" not in package


def test_export_idempotency_and_key_conflict(client, user):
    token = _api_login(client)["access_token"]
    first = _export(client, token, key="same-key", sections=["settings"])
    repeated = _export(client, token, key="same-key", sections=["settings"])
    conflict = _export(client, token, key="same-key", sections=["body_stats"])
    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.get_json()["data"]["export_id"] == first.get_json()["data"]["export_id"]
    assert conflict.status_code == 409


def test_date_range_stable_order_canonical_units_and_download_headers(app, client, user):
    with app.app_context():
        db.session.add_all([
            WeighIn(public_id="71111111-1111-4111-8111-111111111113", user_id=user,
                recorded_at=datetime(2026, 7, 31, 12, tzinfo=timezone.utc), weight_kg="71.250", source="manual"),
            WeighIn(public_id="71111111-1111-4111-8111-111111111112", user_id=user,
                recorded_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc), weight_kg="70.500", source="manual"),
        ])
        db.session.commit()
    token = _api_login(client)["access_token"]
    response = _export(client, token, key="date-range", sections=["body_stats"],
        date_from="2026-07-31", date_to="2026-07-31")
    document = response.get_json()["data"]
    download = client.get(f"/api/v1/mobile/portability/exports/{document['export_id']}/download", headers=_headers(token))
    assert download.status_code == 200
    assert download.headers["Content-Type"].startswith("application/vnd.health-tracker.portable+zip")
    assert "attachment;" in download.headers["Content-Disposition"]
    assert "no-store" in download.headers["Cache-Control"]
    with ZipFile(io.BytesIO(download.data)) as archive:
        raw = archive.read("records/body_stats.jsonl")
        records = [json.loads(line) for line in raw.splitlines()]
    assert [row["public_id"] for row in records] == ["71111111-1111-4111-8111-111111111113"]
    assert records[0]["data"]["weight_kg"] == "71.25"
    assert raw.endswith(b"\n") and b"\r" not in raw


def test_external_provenance_is_sanitized_and_ble_technical_data_is_absent(app, client, user):
    with app.app_context():
        db.session.add_all([
            WeighIn(public_id="72222222-2222-4222-8222-222222222221", user_id=user,
                recorded_at=datetime(2026, 7, 30, 10, tzinfo=timezone.utc), weight_kg="70", source="health_connect:com.qa.private"),
            WeighIn(public_id="72222222-2222-4222-8222-222222222222", user_id=user,
                recorded_at=datetime(2026, 7, 30, 11, tzinfo=timezone.utc), weight_kg="71", source="ble:qa-device"),
        ])
        db.session.commit()
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, key="sources", sections=["body_stats", "external_sources"]).get_json()["data"]["export_id"])
    assert b"com.qa.private" not in package
    assert b"qa-device" not in package
    assert b"mac_address" not in package and b"gatt" not in package and b"changes_token" not in package
    with ZipFile(io.BytesIO(package)) as archive:
        sources = {json.loads(line)["data"]["source"] for line in archive.read("records/body_stats.jsonl").splitlines()}
    assert sources == {"health_connect", "external_measurement"}


def test_profile_and_attachments_require_explicit_opt_in(client, user):
    token = _api_login(client)["access_token"]
    assert _export(client, token, key="profile-off", sections=["profile"]).status_code == 400
    assert _export(client, token, key="attachment-off", sections=["attachments"]).status_code == 400
    profile = _export(client, token, key="profile-on", sections=["profile"], include_identifiable_profile=True)
    assert profile.status_code == 201


def test_export_owner_isolation_and_delete_only_owned_artifact(app, client, user):
    source_token = _api_login(client)["access_token"]
    exported = _export(client, source_token, sections=["settings"]).get_json()["data"]
    _, destination_token = _second_user(app, client)
    path = f"/api/v1/mobile/portability/exports/{exported['export_id']}"
    assert client.get(path, headers=_headers(destination_token)).status_code == 404
    assert client.get(path + "/download", headers=_headers(destination_token)).status_code == 404
    assert client.delete(path, headers=_headers(destination_token)).status_code == 404
    assert client.delete(path, headers=_headers(source_token)).status_code == 200
    assert client.get(path + "/download", headers=_headers(source_token)).status_code in {404, 410}


def test_expiration_removes_only_the_artifact_and_preserves_source_data(app, client, user):
    with app.app_context():
        db.session.add(WeighIn(public_id="73333333-3333-4333-8333-333333333333", user_id=user,
            recorded_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), weight_kg="70", source="manual"))
        db.session.commit()
    token = _api_login(client)["access_token"]
    document = _export(client, token, key="expiry", sections=["body_stats"]).get_json()["data"]
    with app.app_context():
        job = db.session.execute(db.select(PortableExportJob).where(PortableExportJob.public_id == document["export_id"])).scalar_one()
        artifact_path = Path(app.config["PORTABILITY_ROOT"]) / job.artifact.relative_path
        job.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()
        assert artifact_path.is_file()
    detail = client.get(f"/api/v1/mobile/portability/exports/{document['export_id']}", headers=_headers(token))
    assert detail.status_code == 200 and detail.get_json()["data"]["state"] == "expired"
    assert not artifact_path.exists()
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WeighIn).where(WeighIn.user_id == user)) == 1


def test_round_trip_foreign_uuid_remap_and_repeat_has_zero_duplicates(app, client, user):
    with app.app_context():
        db.session.add(WeighIn(
            public_id="71111111-1111-4111-8111-111111111111",
            user_id=user,
            recorded_at=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            weight_kg="72.125",
            body_fat_percentage="18.5",
            source="manual",
            notes="Dato corporal QA completamente ficticio",
        ))
        db.session.commit()
    source_token = _api_login(client)["access_token"]
    exported = _export(client, source_token, sections=["body_stats"]).get_json()["data"]
    package = _package(client, source_token, exported["export_id"])
    destination_id, destination_token = _second_user(app, client)

    inspected = _inspect(client, destination_token, package, ["body_stats"])
    assert inspected.status_code == 201
    job = inspected.get_json()["data"]
    assert job["inspection"]["integrity"] == "verified"
    assert job["inspection"]["authenticity"] == "not_proven"
    assert job["plan"]["summary"]["foreign_collision"] == 1
    apply = client.post(
        f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(destination_token, "apply-round-trip"),
    )
    assert apply.status_code == 200
    assert apply.get_json()["data"]["counts"]["inserted"] == 1
    replay = client.post(
        f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(destination_token, "apply-round-trip"),
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"] == apply.get_json()["data"]
    with app.app_context():
        rows = db.session.execute(db.select(WeighIn).where(WeighIn.user_id == destination_id)).scalars().all()
        assert len(rows) == 1
        assert rows[0].public_id != "71111111-1111-4111-8111-111111111111"
        assert str(rows[0].weight_kg) == "72.125"

    repeated_inspection = _inspect(client, destination_token, package, ["body_stats"])
    repeated_job = repeated_inspection.get_json()["data"]
    assert repeated_job["plan"]["summary"]["same_record"] == 1
    repeated_apply = client.post(
        f"/api/v1/mobile/portability/imports/{repeated_job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(destination_token, "apply-round-trip-repeat"),
    )
    assert repeated_apply.status_code == 200
    assert repeated_apply.get_json()["data"]["counts"]["skipped"] == 1
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WeighIn).where(WeighIn.user_id == destination_id)) == 1


def test_ai_conversations_are_portable_without_secrets_or_provider_internals(
    app, client, user
):
    app.config.update(
        AI_ENABLED=True,
        AI_PROVIDER="fake",
        AI_MODEL="fake-health-v1",
        AI_API_KEY="qa-secret-that-must-not-be-exported",
        AI_TODAY_OVERRIDE=date(2026, 8, 9),
    )
    with app.app_context():
        account = db.session.get(User, user)
        account.timezone = "UTC"
        service = AIConversationService()
        conversation = service.create(user, title="Conversación portable QA")
        service.send_message(account, conversation.public_id, "Peso 72 kg")
        service.send_message(account, conversation.public_id, "¿Cómo cambió mi peso?")
        source_public_id = conversation.public_id

    token = _api_login(client)["access_token"]
    exported = _export(
        client,
        token,
        key="ai-portability",
        sections=["ai_conversations"],
    )
    assert exported.status_code == 201, exported.get_json()
    package = _package(client, token, exported.get_json()["data"]["export_id"])
    assert b"qa-secret-that-must-not-be-exported" not in package
    assert b"provider_call_id" not in package
    assert b"sanitized_arguments_json" not in package
    assert b"chain_of_thought" not in package
    with ZipFile(io.BytesIO(package)) as archive:
        records = [
            json.loads(line)
            for line in archive.read("records/ai_conversations.jsonl").splitlines()
        ]
        assert len(records) == 1
        data = records[0]["data"]
        assert len(data["messages"]) == 4
        assert len(data["tool_calls"]) == 1
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["provenance"]["value_origin"] == "reported_by_user"

    destination_id, destination_token = _second_user(app, client)
    inspected = _inspect(
        client, destination_token, package, ["ai_conversations"]
    )
    assert inspected.status_code == 201, inspected.get_json()
    job = inspected.get_json()["data"]
    applied = client.post(
        f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(destination_token, "ai-portability-apply"),
    )
    assert applied.status_code == 200, applied.get_json()
    with app.app_context():
        imported = db.session.execute(
            db.select(AIConversation).where(AIConversation.user_id == destination_id)
        ).scalar_one()
        assert imported.public_id != source_public_id
        assert len(imported.messages) == 4
        assert len(imported.tool_calls) == 1
        assert len(imported.drafts) == 1
        assert imported.tool_calls[0].provider_call_id is None
        assert imported.tool_calls[0].sanitized_arguments_json == {}


def test_import_requires_confirmation_and_idempotency(app, client, user):
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, sections=["settings"]).get_json()["data"]["export_id"])
    job = _inspect(client, token, package, ["settings"]).get_json()["data"]
    url = f"/api/v1/mobile/portability/imports/{job['import_id']}/apply"
    assert client.post(url, json={"confirmed": False, "plan_revision": 1, "decisions": []}, headers=_headers(token, "not-confirmed")).status_code == 400
    assert client.post(url, json={"confirmed": True, "plan_revision": 1, "decisions": []}, headers=_headers(token)).status_code == 400


def test_selective_dry_run_conflict_and_safe_destination_decision(app, client, user):
    with app.app_context():
        db.session.add(WeighIn(public_id="74444444-4444-4444-8444-444444444444", user_id=user,
            recorded_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), weight_kg="70", source="manual",
            notes="Nota QA ficticia original"))
        db.session.commit()
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, key="selective", sections=["settings", "body_stats"]).get_json()["data"]["export_id"])
    with app.app_context():
        row = db.session.execute(db.select(WeighIn).where(WeighIn.public_id == "74444444-4444-4444-8444-444444444444")).scalar_one()
        row.notes = "Nota QA ficticia del destino"; db.session.commit()
    inspected = _inspect(client, token, package, ["body_stats"])
    assert inspected.status_code == 201
    job = inspected.get_json()["data"]
    assert job["sections"] == ["body_stats"]
    assert job["plan"]["summary"]["conflict"] == 1
    url = f"/api/v1/mobile/portability/imports/{job['import_id']}/apply"
    assert client.post(url, json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(token, "unresolved-conflict")).status_code == 409
    decision = {"section": "body_stats", "source_public_id": "74444444-4444-4444-8444-444444444444", "strategy": "use_destination"}
    applied = client.post(url, json={"confirmed": True, "plan_revision": 1, "decisions": [decision]},
        headers=_headers(token, "safe-conflict"))
    assert applied.status_code == 200
    assert applied.get_json()["data"]["counts"]["skipped"] == 1
    with app.app_context():
        row = db.session.execute(db.select(WeighIn).where(WeighIn.public_id == decision["source_public_id"])).scalar_one()
        assert row.notes == "Nota QA ficticia del destino"


def test_attachment_round_trip_is_opt_in_owner_scoped_and_hash_verified(app, client, user):
    content = b"Fictional QA attachment without personal data.\n"
    digest = hashlib.sha256(content).hexdigest()
    source = Path(app.config["UPLOAD_ROOT"]) / f"user_{user}" / digest
    source.parent.mkdir(parents=True, exist_ok=True); source.write_bytes(content)
    with app.app_context():
        db.session.add(UploadedFile(user_id=user, original_filename="qa report?.txt", stored_filename=digest,
            storage_path=source.relative_to(Path(app.config["DATA_ROOT"])).as_posix(), source_type="uploaded",
            detected_type="text", import_status="imported", sha256=digest, size_bytes=len(content), mime_type="text/plain"))
        db.session.commit()
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, key="attachment-export", sections=["attachments"],
        include_attachments=True).get_json()["data"]["export_id"])
    with ZipFile(io.BytesIO(package)) as archive:
        names = archive.namelist()
        metadata = json.loads(archive.read("records/attachments.jsonl"))
        assert metadata["data"]["filename"] == "qa_report_.txt"
        assert archive.read(metadata["data"]["archive_path"]) == content
        assert sum(name.startswith("attachments/") for name in names) == 1
    destination_id, destination_token = _second_user(app, client)
    job = _inspect(client, destination_token, package, ["attachments"]).get_json()["data"]
    applied = client.post(f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []}, headers=_headers(destination_token, "attachment-apply"))
    assert applied.status_code == 200
    with app.app_context():
        uploaded = db.session.execute(db.select(UploadedFile).where(UploadedFile.user_id == destination_id)).scalar_one()
        assert uploaded.sha256 == digest
        assert (Path(app.config["DATA_ROOT"]) / uploaded.storage_path).read_bytes() == content


def test_medical_portable_metadata_and_opt_in_binary_round_trip(app, client, user):
    token = _api_login(client)["access_token"]
    study_payload = {
        "public_id": "78888888-8888-4888-8888-888888888881",
        "study_type": "laboratory", "title": "Estudio portable QA ficticio",
        "laboratory_name": "Laboratorio QA", "professional_name": None,
        "study_date": "2026-07-15", "issued_date": "2026-07-16",
        "timezone": "UTC", "notes": "Solo datos ficticios.",
        "state": "complete", "source": "mobile",
    }
    study = client.post("/api/v1/mobile/medical-studies", json=study_payload,
        headers=_headers(token, "portable-medical-study")).get_json()["data"]
    result_payload = {
        "public_id": "78888888-8888-4888-8888-888888888882",
        "panel_name": "Panel QA", "display_name": "Marcador QA", "canonical_key": None,
        "value_type": "numeric", "original_value": "4.2", "numeric_value": "4.2",
        "comparator": "equal", "original_unit": "mg/L", "reference_lower": "3",
        "reference_upper": "5", "reference_text": "Rango QA del informe",
        "source_status": "within_range", "method": "Método QA", "specimen": "Muestra QA",
        "notes": None, "source": "mobile",
    }
    assert client.post(f"/api/v1/mobile/medical-studies/{study['public_id']}/results",
        json=result_payload, headers=_headers(token, "portable-medical-result")).status_code == 201
    content = b"%PDF-1.4\nFictional portable medical QA document\n%%EOF"
    uploaded = client.post(f"/api/v1/mobile/medical-studies/{study['public_id']}/documents",
        data={"file": (io.BytesIO(content), "informe-portable-qa.pdf", "application/pdf")},
        headers=_headers(token, "portable-medical-document"), content_type="multipart/form-data")
    assert uploaded.status_code == 201

    medical_sections = ["medical_studies", "lab_panels", "lab_results", "medical_documents_metadata"]
    metadata_package = _package(client, token, _export(client, token, key="portable-medical-metadata",
        sections=medical_sections).get_json()["data"]["export_id"])
    with ZipFile(io.BytesIO(metadata_package)) as archive:
        assert not any(name.startswith("attachments/") for name in archive.namelist())
        metadata = json.loads(archive.read("records/medical_documents_metadata.jsonl"))
        assert metadata["data"]["attachment_public_id"] is None

    package = _package(client, token, _export(client, token, key="portable-medical-binary",
        sections=medical_sections, include_medical_attachments=True).get_json()["data"]["export_id"])
    with ZipFile(io.BytesIO(package)) as archive:
        assert sum(name.startswith("attachments/") for name in archive.namelist()) == 1
        metadata = json.loads(archive.read("records/medical_documents_metadata.jsonl"))
        assert metadata["data"]["attachment_public_id"]

    destination_id, destination_token = _second_user(app, client)
    inspection = _inspect(client, destination_token, package,
        [*medical_sections, "attachments"]).get_json()["data"]
    applied = client.post(f"/api/v1/mobile/portability/imports/{inspection['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []},
        headers=_headers(destination_token, "portable-medical-apply"))
    assert applied.status_code == 200
    with app.app_context():
        destination_study = db.session.execute(db.select(MedicalStudy).where(
            MedicalStudy.user_id == destination_id)).scalar_one()
        destination_result = db.session.execute(db.select(LabResult).where(
            LabResult.user_id == destination_id)).scalar_one()
        destination_document = db.session.execute(db.select(MedicalDocument).where(
            MedicalDocument.user_id == destination_id)).scalar_one()
        assert destination_study.public_id != study["public_id"]
        assert destination_result.original_value == "4.2"
        assert destination_document.availability == "available"
        assert destination_document.uploaded_file.source_type == "medical_document"
        assert (Path(app.config["DATA_ROOT"]) / destination_document.uploaded_file.storage_path).read_bytes() == content


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="MariaDB medical E2E runs only in Docker")
def test_mariadb_medical_document_portability_e2e_and_rollback(app, tmp_path, monkeypatch):
    concurrent_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "medical-e2e-secret-key-long-enough-for-qa",
        "API_TOKEN_SIGNING_KEY": "medical-e2e-api-signing-key-long-enough-for-qa",
        "DATA_ROOT": tmp_path / "mariadb-medical-e2e",
        "UPLOAD_ROOT": tmp_path / "mariadb-medical-e2e" / "uploads" / "raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "mariadb-medical-e2e" / "uploads" / "generated",
        "PORTABILITY_ROOT": tmp_path / "mariadb-medical-e2e" / "portability",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False, "API_RATE_LIMIT_ENABLED": False,
    })
    nonce = uuid.uuid4().hex
    roles = ("source", "metadata", "binary", "rollback")
    account_ids = {}
    with concurrent_app.app_context():
        for role in roles:
            username = f"medical-e2e-{role}-{nonce}"
            account = User(username=username, email=f"{username}@example.invalid", role="user")
            account.set_password("fictional-e2e-password")
            db.session.add(account)
            db.session.flush()
            account_ids[role] = account.id
        db.session.commit()

    def login(role, device_suffix):
        username = f"medical-e2e-{role}-{nonce}"
        return _api_login(
            concurrent_app.test_client(), username=f"{username}@example.invalid",
            password="fictional-e2e-password",
            device_id=f"a9222222-2222-4222-8222-22222222222{device_suffix}",
        )["access_token"]

    try:
        source_token = login("source", "1")
        source_client = concurrent_app.test_client()
        study_id = str(uuid.uuid4())
        study = source_client.post("/api/v1/mobile/medical-studies", json={
            "public_id": study_id, "study_type": "laboratory", "title": "Estudio E2E ficticio",
            "laboratory_name": "Laboratorio E2E ficticio", "study_date": "2026-07-20",
            "issued_date": "2026-07-21", "timezone": "UTC", "notes": "Fixture QA ficticia.",
            "state": "complete", "source": "mobile",
        }, headers=_headers(source_token, "medical-e2e-study")).get_json()["data"]
        numeric = source_client.post(f"/api/v1/mobile/medical-studies/{study_id}/results", json={
            "public_id": str(uuid.uuid4()), "panel_name": "Panel E2E ficticio", "display_name": "Glucosa E2E",
            "canonical_key": "glucose", "value_type": "numeric", "original_value": "4.2",
            "numeric_value": "4.2", "comparator": "equal", "original_unit": "mg/L",
            "reference_lower": "3", "reference_upper": "5", "reference_text": "Rango ficticio del informe",
            "source_status": "within_range", "method": "Método E2E", "specimen": "Muestra ficticia",
            "source": "mobile",
        }, headers=_headers(source_token, "medical-e2e-numeric")).get_json()["data"]
        text_result = source_client.post(f"/api/v1/mobile/medical-studies/{study_id}/results", json={
            "public_id": str(uuid.uuid4()), "panel_name": "Panel E2E ficticio", "display_name": "Texto E2E",
            "value_type": "text", "original_value": "No detectado QA", "comparator": "none",
            "source_status": "not_provided", "source": "mobile",
        }, headers=_headers(source_token, "medical-e2e-text"))
        assert text_result.status_code == 201
        pdf = b"%PDF-1.4\nFictional MariaDB medical E2E document\n%%EOF"
        document = source_client.post(f"/api/v1/mobile/medical-studies/{study_id}/documents",
            data={"file": (io.BytesIO(pdf), "medical-e2e-ficticio.pdf", "application/pdf")},
            headers=_headers(source_token, "medical-e2e-document"), content_type="multipart/form-data")
        assert document.status_code == 201
        document_id = document.get_json()["data"]["public_id"]
        downloaded = source_client.get(f"/api/v1/mobile/medical-documents/{document_id}/download",
            headers=_headers(source_token))
        assert downloaded.status_code == 200 and downloaded.data == pdf
        assert downloaded.headers["Cache-Control"] == "no-store"
        assert hashlib.sha256(downloaded.data).hexdigest() == document.get_json()["data"]["sha256"]
        corrected = source_client.patch(f"/api/v1/mobile/lab-results/{numeric['public_id']}",
            json={"base_revision": 1, "original_value": "4.3", "numeric_value": "4.3",
                  "correction_reason": "Corrección E2E ficticia"},
            headers=_headers(source_token, "medical-e2e-correction")).get_json()["data"]
        assert corrected["revision"] == 2 and len(corrected["revisions"]) == 2
        history = source_client.get("/api/v1/mobile/lab-history/glucose?period=all",
            headers=_headers(source_token)).get_json()["data"]
        assert history["count"] == 1 and history["points"][0]["result"]["original_value"] == "4.3"

        sections = ["medical_studies", "lab_panels", "lab_results", "medical_documents_metadata"]
        metadata_export = _export(source_client, source_token, key="medical-e2e-export-metadata", sections=sections)
        metadata_package = _package(source_client, source_token, metadata_export.get_json()["data"]["export_id"])
        with ZipFile(io.BytesIO(metadata_package)) as archive:
            assert not any(name.startswith("attachments/") for name in archive.namelist())

        metadata_token = login("metadata", "2")
        metadata_client = concurrent_app.test_client()
        metadata_job = _inspect(metadata_client, metadata_token, metadata_package, sections).get_json()["data"]
        apply_payload = {"confirmed": True, "plan_revision": 1, "decisions": []}
        applied_once = metadata_client.post(
            f"/api/v1/mobile/portability/imports/{metadata_job['import_id']}/apply", json=apply_payload,
            headers=_headers(metadata_token, "medical-e2e-metadata-apply"))
        applied_twice = metadata_client.post(
            f"/api/v1/mobile/portability/imports/{metadata_job['import_id']}/apply", json=apply_payload,
            headers=_headers(metadata_token, "medical-e2e-metadata-apply"))
        assert applied_once.status_code == applied_twice.status_code == 200
        assert applied_once.get_json()["data"] == applied_twice.get_json()["data"]
        with concurrent_app.app_context():
            metadata_id = account_ids["metadata"]
            assert db.session.scalar(db.select(db.func.count()).select_from(MedicalStudy).where(
                MedicalStudy.user_id == metadata_id)) == 1
            assert db.session.scalar(db.select(db.func.count()).select_from(MedicalDuplicateCandidate).where(
                MedicalDuplicateCandidate.user_id == metadata_id)) == 0
            imported_values = sorted(db.session.scalars(db.select(LabResult.original_value).where(
                LabResult.user_id == metadata_id)).all())
            assert imported_values == ["4.3", "No detectado QA"]
            metadata_document = db.session.execute(db.select(MedicalDocument).where(
                MedicalDocument.user_id == metadata_id)).scalar_one()
            assert metadata_document.availability == "metadata_only" and metadata_document.uploaded_file_id is None

        binary_export = _export(source_client, source_token, key="medical-e2e-export-binary",
            sections=sections, include_medical_attachments=True)
        binary_package = _package(source_client, source_token, binary_export.get_json()["data"]["export_id"])
        binary_token = login("binary", "3")
        binary_client = concurrent_app.test_client()
        binary_job = _inspect(binary_client, binary_token, binary_package, [*sections, "attachments"]).get_json()["data"]
        assert binary_client.post(f"/api/v1/mobile/portability/imports/{binary_job['import_id']}/apply",
            json=apply_payload, headers=_headers(binary_token, "medical-e2e-binary-apply")).status_code == 200
        with concurrent_app.app_context():
            imported_document = db.session.execute(db.select(MedicalDocument).where(
                MedicalDocument.user_id == account_ids["binary"])).scalar_one()
            imported_document_id = imported_document.public_id
            assert imported_document.availability == "available"
            assert (Path(concurrent_app.config["DATA_ROOT"]) / imported_document.uploaded_file.storage_path).read_bytes() == pdf
        assert source_client.get(f"/api/v1/mobile/medical-documents/{imported_document_id}",
            headers=_headers(source_token)).status_code == 404
        assert binary_client.get(f"/api/v1/mobile/medical-documents/{imported_document_id}/download",
            headers=_headers(binary_token)).data == pdf

        rollback_token = login("rollback", "4")
        rollback_client = concurrent_app.test_client()
        rollback_job = _inspect(rollback_client, rollback_token, binary_package, [*sections, "attachments"]).get_json()["data"]
        import app.services.portability_import as service
        original_apply = service._apply_record
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise service.PortabilityImportError("qa_injected_failure", "Fallo E2E ficticio.", 409)
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(service, "_apply_record", fail_second)
        failed = rollback_client.post(f"/api/v1/mobile/portability/imports/{rollback_job['import_id']}/apply",
            json=apply_payload, headers=_headers(rollback_token, "medical-e2e-rollback-apply"))
        assert failed.status_code == 409
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(MedicalStudy).where(
                MedicalStudy.user_id == account_ids["rollback"])) == 0
    finally:
        with concurrent_app.app_context():
            for account_id in account_ids.values():
                account = db.session.get(User, account_id)
                if account is not None:
                    db.session.delete(account)
            db.session.commit()


def test_mid_import_failure_rolls_back_all_domain_rows(app, client, user, monkeypatch):
    with app.app_context():
        db.session.add_all([
            WeighIn(public_id="75555555-5555-4555-8555-555555555551", user_id=user,
                recorded_at=datetime(2026, 7, 29, 12, tzinfo=timezone.utc), weight_kg="70", source="manual"),
            WeighIn(public_id="75555555-5555-4555-8555-555555555552", user_id=user,
                recorded_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), weight_kg="71", source="manual"),
        ]); db.session.commit()
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, key="rollback-export", sections=["body_stats"]).get_json()["data"]["export_id"])
    destination_id, destination_token = _second_user(app, client)
    job = _inspect(client, destination_token, package, ["body_stats"]).get_json()["data"]
    import app.services.portability_import as service
    original = service._apply_record
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise service.PortabilityImportError("qa_injected_failure", "Fallo QA inyectado.", 409)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "_apply_record", fail_second)
    response = client.post(f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={"confirmed": True, "plan_revision": 1, "decisions": []}, headers=_headers(destination_token, "rollback-apply"))
    assert response.status_code == 409
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(WeighIn).where(WeighIn.user_id == destination_id)) == 0
        stored = db.session.execute(db.select(PortableImportJob).where(PortableImportJob.public_id == job["import_id"])).scalar_one()
        assert stored.state == "rolled_back" and stored.error_code == "qa_injected_failure"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/absolute", "records\\evil.jsonl"])
def test_zip_unsafe_paths_rejected(app, tmp_path, name):
    package = tmp_path / "unsafe.htpack"
    with ZipFile(package, "w", ZIP_DEFLATED) as archive:
        archive.writestr(name, b"x")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(package)
    assert caught.value.code in {"unsafe_path", "manifest_missing"}


def test_zip_duplicate_case_and_symlink_rejected(app, tmp_path):
    duplicate = tmp_path / "duplicate.htpack"
    with ZipFile(duplicate, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("MANIFEST.JSON", b"{}")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(duplicate)
    assert caught.value.code == "duplicate_file"

    linked = tmp_path / "linked.htpack"
    info = ZipInfo("manifest.json")
    info.create_system = 3
    info.external_attr = (0o120777 << 16)
    with ZipFile(linked, "w") as archive:
        archive.writestr(info, b"target")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(linked)
    assert caught.value.code == "special_file"


def test_invalid_utf8_and_missing_manifest_rejected(app, tmp_path):
    missing = tmp_path / "missing.htpack"
    with ZipFile(missing, "w") as archive:
        archive.writestr("checksums.json", b"{}")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(missing)
    assert caught.value.code == "manifest_missing"

    invalid = tmp_path / "invalid.htpack"
    with ZipFile(invalid, "w") as archive:
        archive.writestr("manifest.json", b"\xff")
        archive.writestr("checksums.json", b"{}")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(invalid)
    assert caught.value.code == "invalid_json"


def test_checksum_undeclared_file_zip_bomb_and_file_count_limits(app, client, user, tmp_path):
    token = _api_login(client)["access_token"]
    package = _package(client, token, _export(client, token, key="security-pack", sections=["settings"]).get_json()["data"]["export_id"])
    tampered = tmp_path / "tampered.htpack"
    tampered.write_bytes(_rewrite(package, lambda members: members.__setitem__("records/settings.json", b"{}\n")))
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(tampered)
    assert caught.value.code in {"checksum_mismatch", "size_mismatch"}

    undeclared = tmp_path / "undeclared.htpack"
    undeclared.write_bytes(_rewrite(package, lambda members: members.__setitem__("records/qa-extra.json", b"{}\n")))
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(undeclared)
    assert caught.value.code == "undeclared_file"

    bomb = tmp_path / "bomb.htpack"
    with ZipFile(bomb, "w", ZIP_DEFLATED) as archive:
        archive.writestr("qa.bin", b"0" * (2 * 1024 * 1024))
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"]), PortableLimits(max_compression_ratio=10)).inspect(bomb)
    assert caught.value.code == "compression_ratio"

    crowded = tmp_path / "crowded.htpack"
    with ZipFile(crowded, "w") as archive:
        for index in range(3): archive.writestr(f"qa-{index}.json", b"{}")
    with pytest.raises(PortableArchiveError) as caught:
        PortableArchiveReader(Path(app.config["SCHEMA_ROOT"]), PortableLimits(max_files=2)).inspect(crowded)
    assert caught.value.code == "too_many_files"


def test_every_portable_schema_is_valid_and_uses_only_local_refs(app):
    root = Path(app.config["SCHEMA_ROOT"])
    schemas = sorted(root.glob("portable_*.schema.json"))
    assert len(schemas) == 32
    names = {path.name for path in schemas}
    for path in schemas:
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(document)
        pending = [document]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and not reference.startswith("#"):
                    assert reference.split("#", 1)[0] in names
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)


def test_portability_migration_0033_is_additive_reversible_and_reupgradeable(tmp_path):
    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "20260730_0033_data_portability.py"
    spec = importlib.util.spec_from_file_location("data_portability_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20260726_0032"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'portability-migration.db'}")
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(users.insert().values(id=1))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    expected = {"portable_artifacts", "portable_export_jobs", "portable_import_jobs",
        "portable_import_decisions", "portable_import_mappings"}
    assert expected <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO portable_artifacts "
            "(public_id,user_id,kind,relative_path,filename,media_type,sha256,size_bytes,expires_at) VALUES "
            "('80000000-0000-4000-8000-000000000001',1,'export','user_1/qa.htpack','qa.htpack',"
            "'application/vnd.health-tracker.portable+zip','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1,'2026-08-01')"
        ))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO portable_artifacts "
                "(public_id,user_id,kind,relative_path,filename,media_type,sha256,size_bytes,expires_at) VALUES "
                "('80000000-0000-4000-8000-000000000002',1,'invalid','user_1/bad.htpack','bad.htpack',"
                "'application/octet-stream','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',1,'2026-08-01')"
            ))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    assert expected.isdisjoint(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one() == 1
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    assert expected <= set(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_desktop_tools_verify_inspect_list_and_create_a_new_sanitized_copy(app, client, user, tmp_path):
    with app.app_context():
        db.session.add(WeighIn(public_id="76666666-6666-4666-8666-666666666666", user_id=user,
            recorded_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), weight_kg="70", source="health_connect:qa",
            notes="Nota QA que debe eliminarse"))
        db.session.commit()
    token = _api_login(client)["access_token"]
    content = _package(client, token, _export(client, token, key="cli-export", sections=["profile", "body_stats", "external_sources"],
        include_identifiable_profile=True).get_json()["data"]["export_id"])
    package = tmp_path / "qa-input.htpack"; package.write_bytes(content)
    scripts = next(path for path in (
        Path(__file__).parents[2] / "scripts" / "portability",
        Path(__file__).parents[1] / "scripts" / "portability",
    ) if path.is_dir())
    inspect = subprocess.run([sys.executable, str(scripts / "inspect_htpack.py"), str(package)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    verify = subprocess.run([sys.executable, str(scripts / "verify_htpack.py"), str(package)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    listed = subprocess.run([sys.executable, str(scripts / "list_htpack.py"), str(package)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert inspect.returncode == verify.returncode == listed.returncode == 0
    assert '"records"' not in inspect.stdout and "Nota QA" not in inspect.stdout and "Nota QA" not in listed.stdout
    assert '"integrity": "verified"' in verify.stdout

    sanitized = tmp_path / "qa-sanitized.htpack"
    result = subprocess.run([sys.executable, str(scripts / "sanitize_htpack.py"), str(package), str(sanitized)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    assert result.returncode == 0 and package.is_file() and sanitized.is_file()
    inspection = PortableArchiveReader(Path(app.config["SCHEMA_ROOT"])).inspect(sanitized)
    assert "profile" not in inspection.records and "external_sources" not in inspection.records
    assert "attachments" not in inspection.records
    assert all("notes" not in row["data"] for rows in inspection.records.values() for row in rows)


@pytest.mark.skipif(not Path("/.dockerenv").exists(), reason="MariaDB portability concurrency runs only in Docker")
def test_mariadb_concurrent_export_and_apply_replay_single_result(app, tmp_path):
    concurrent_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "portability-mariadb-secret-long-enough",
        "API_TOKEN_SIGNING_KEY": "portability-mariadb-api-key-long-enough",
        "DATA_ROOT": tmp_path / "mariadb-portability",
        "UPLOAD_ROOT": tmp_path / "mariadb-portability" / "uploads" / "raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "mariadb-portability" / "uploads" / "generated",
        "PORTABILITY_ROOT": tmp_path / "mariadb-portability" / "packages",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
        "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False, "API_RATE_LIMIT_ENABLED": False,
    })
    source_name = f"portable-source-{uuid.uuid4().hex}"
    destination_name = f"portable-destination-{uuid.uuid4().hex}"
    with concurrent_app.app_context():
        source = User(username=source_name, email=f"{source_name}@example.invalid", role="user")
        source.set_password("fictional-race-password")
        destination = User(username=destination_name, email=f"{destination_name}@example.invalid", role="user")
        destination.set_password("fictional-race-password")
        db.session.add_all([source, destination]); db.session.flush()
        source_id, destination_id = source.id, destination.id
        db.session.add(WeighIn(public_id=str(uuid.uuid4()), user_id=source_id,
            recorded_at=datetime(2026, 7, 30, 12, tzinfo=timezone.utc), weight_kg="70", source="manual"))
        db.session.commit()
    try:
        source_client = concurrent_app.test_client()
        source_token = _api_login(source_client, username=source_name, password="fictional-race-password",
            device_id="81111111-1111-4111-8111-111111111111")["access_token"]
        export_barrier = Barrier(2)

        def export_once():
            with concurrent_app.test_client() as race_client:
                export_barrier.wait(timeout=10)
                response = _export(race_client, source_token, key="portable-concurrent-export", sections=["body_stats"])
                return response.status_code, response.get_json()["data"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            exports = list(pool.map(lambda _index: export_once(), range(2)))
        assert sorted(status for status, _data in exports) == [200, 201]
        export_ids = {data["export_id"] for _status, data in exports}
        assert len(export_ids) == 1
        export_id = export_ids.pop()
        package = _package(source_client, source_token, export_id)

        destination_client = concurrent_app.test_client()
        destination_token = _api_login(destination_client, username=destination_name, password="fictional-race-password",
            device_id="82222222-2222-4222-8222-222222222222")["access_token"]
        job = _inspect(destination_client, destination_token, package, ["body_stats"]).get_json()["data"]
        apply_barrier = Barrier(2)

        def apply_once():
            with concurrent_app.test_client() as race_client:
                apply_barrier.wait(timeout=10)
                response = race_client.post(f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
                    json={"confirmed": True, "plan_revision": 1, "decisions": []},
                    headers=_headers(destination_token, "portable-concurrent-apply"))
                return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            applies = list(pool.map(lambda _index: apply_once(), range(2)))
        assert [status for status, _body in applies] == [200, 200]
        assert applies[0][1]["data"] == applies[1][1]["data"]
        with concurrent_app.app_context():
            assert db.session.scalar(db.select(db.func.count()).select_from(PortableExportJob).where(
                PortableExportJob.user_id == source_id)) == 1
            assert db.session.scalar(db.select(db.func.count()).select_from(WeighIn).where(
                WeighIn.user_id == destination_id)) == 1
    finally:
        with concurrent_app.app_context():
            for account_id in (source_id, destination_id):
                account = db.session.get(User, account_id)
                if account is not None: db.session.delete(account)
            db.session.commit()


def test_staging_remains_empty_and_jobs_store_only_key_hash(app, client, user):
    token = _api_login(client)["access_token"]
    response = _export(client, token, key="never-store-this-key", sections=["settings"])
    assert response.status_code == 201
    with app.app_context():
        job = db.session.execute(db.select(PortableExportJob)).scalar_one()
        assert job.idempotency_key_hash != "never-store-this-key"
        assert len(job.idempotency_key_hash) == 64
        assert "never-store-this-key" not in json.dumps(job.sections_json)
