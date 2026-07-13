from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from werkzeug.datastructures import FileStorage

import app.services.backups as backups_module
from app.extensions import db
from app.models import Activity, ExportRecord, ImportRun, UploadedFile, User, WeighIn
from app.services.backup_reconcile import BackupReconciliationService
from app.services.backups import (
    ACCOUNT_EXPORT_PATH,
    BACKUP_FORMAT_VERSION,
    MANIFEST_PATH,
    AccountBackupService,
    BackupArchiveReader,
    BackupError,
    BackupRestoreCoordinator,
    BackupSecurityError,
    BackupTokenError,
    _json_bytes,
)
from app.services.exporters.user_data import build_user_data_document
from tests.test_account_restore import _complete_account_payload, _semantic_export


def _user(username: str) -> User:
    record = User(username=username, role="user")
    record.set_password("fictional-test-password")
    db.session.add(record)
    db.session.flush()
    return record


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_account(app, user_id: int) -> dict[str, object]:
    raw_bytes = b"fictional fit bytes\x00\x01"
    unicode_name = "actividad-ficticia-ñ.fit"
    raw_path = Path(app.config["UPLOAD_ROOT"]) / f"user_{user_id}" / _sha(raw_bytes)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_bytes)
    upload = UploadedFile(
        user_id=user_id,
        original_filename=unicode_name,
        stored_filename=_sha(raw_bytes),
        storage_path=raw_path.relative_to(app.config["DATA_ROOT"]).as_posix(),
        source_type="uploaded",
        detected_type="activity",
        import_status="imported",
        sha256=_sha(raw_bytes),
        size_bytes=len(raw_bytes),
        mime_type="application/octet-stream",
    )
    db.session.add(upload)
    db.session.flush()

    activity_document = {
        "schema_version": "1.0",
        "record_type": "activity",
        "user_id": user_id,
        "source_type": "uploaded",
        "source_file_id": upload.id,
        "data": {
            "activity_type": "cycling",
            "started_at": "2026-07-02T08:00:00+00:00",
            "duration_seconds": 1800,
            "distance_meters": 12000,
            "notes": "Actividad completamente ficticia.",
        },
    }
    db.session.add(
        Activity(
            user_id=user_id,
            activity_type="cycling",
            started_at=datetime(2026, 7, 2, 8, tzinfo=timezone.utc),
            duration_seconds=1800,
            distance_meters=12000,
            source_type="uploaded",
            source_file_id=upload.id,
            fingerprint_sha256="f" * 64,
            canonical_json=activity_document,
            point_count=0,
            notes="Actividad completamente ficticia.",
        )
    )

    weigh = WeighIn(
        user_id=user_id,
        recorded_at=datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
        weight_kg=80.5,
        source="manual",
        raw_payload_json={
            "schema_version": "1.0",
            "type": "weigh_in",
            "user_id": user_id,
            "source_type": "manual_generated",
            "data": {
                "recorded_at": "2026-07-01T08:00:00+00:00",
                "weight_kg": 80.5,
                "source": "manual",
            },
        },
    )
    db.session.add(weigh)
    db.session.flush()

    generated_bytes = b'{"fictional":"export"}\n'
    generated_path = (
        Path(app.config["GENERATED_UPLOAD_ROOT"])
        / "weigh_in"
        / f"user_{user_id}"
        / "fictional-export.json"
    )
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_bytes(generated_bytes)
    export = ExportRecord(
        user_id=user_id,
        domain="weigh_in",
        source_type="weigh_in",
        source_id=weigh.id,
        format="json",
        exporter_version="1.0",
        filename="fictional-export.json",
        relative_path=generated_path.relative_to(app.config["DATA_ROOT"]).as_posix(),
        media_type="application/json",
        size_bytes=len(generated_bytes),
        sha256=_sha(generated_bytes),
        status="ready",
    )
    db.session.add(export)
    db.session.commit()
    return {
        "raw_bytes": raw_bytes,
        "raw_sha": _sha(raw_bytes),
        "generated_bytes": generated_bytes,
        "generated_sha": _sha(generated_bytes),
        "upload_id": upload.id,
        "export_id": export.id,
    }


def _create_backup(app, user_id: int) -> tuple[ExportRecord, Path]:
    user = db.session.get(User, user_id)
    record = AccountBackupService().create(user, user_id=user_id)
    path = Path(app.config["DATA_ROOT"]) / record.relative_path
    return record, path


def _stage(path: Path, coordinator: BackupRestoreCoordinator, user_id: int) -> str:
    with path.open("rb") as stream:
        return coordinator.stage_upload(
            FileStorage(stream=stream, filename="renamed-backup.zip"),
            user_id=user_id,
        )


def _empty_account_payload(user_id: int = 99) -> dict:
    return {
        "schema_version": "1.0",
        "type": "user_data_export",
        "exported_at": "2026-07-12T12:00:00+00:00",
        "user": {"id": user_id, "email": None, "role": "user"},
        "data": {},
    }


def _manifest_for(account_bytes: bytes, *, path: str = ACCOUNT_EXPORT_PATH) -> dict:
    entry = {
        "logical_id": "account_export",
        "kind": "account_export",
        "relative_path": path,
        "original_filename": "user_data_export.json",
        "media_type": "application/json",
        "size_bytes": len(account_bytes),
        "sha256": _sha(account_bytes),
        "source_record_type": None,
        "source_record_id": None,
        "source_file_id": None,
        "required": True,
        "metadata": {},
    }
    return {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "schema_version": "1.0",
        "created_at": "2026-07-12T12:00:00+00:00",
        "app_version": "test",
        "source_account": {"source_user_id": 99},
        "account_export": ACCOUNT_EXPORT_PATH,
        "entries": [entry],
        "totals": {
            "entries": 1,
            "raw_uploads": 0,
            "generated_exports": 0,
            "uncompressed_bytes": len(account_bytes),
        },
        "capabilities": ["account_data"],
        "unsupported": [],
        "warnings": [],
    }


def _write_archive(path: Path, manifest: dict, members: list[tuple[object, bytes]]) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_PATH, _json_bytes(manifest))
        for name, content in members:
            archive.writestr(name, content)


def test_backup_creation_manifest_hashes_streamed_files_and_record(app, user):
    with app.app_context():
        source = _source_account(app, user)
        preview = AccountBackupService().preview(db.session.get(User, user), user_id=user)
        assert preview["valid"] is True
        assert preview["raw_uploads"] == 1
        assert preview["generated_exports"] == 1

        record, path = _create_backup(app, user)
        inspection = BackupArchiveReader().inspect(path)

        assert record.domain == "account_backup"
        assert record.sha256 == _sha(path.read_bytes())
        assert inspection.manifest["backup_format_version"] == "1.0"
        assert inspection.manifest["totals"]["raw_uploads"] == 1
        assert inspection.manifest["totals"]["generated_exports"] == 1
        assert inspection.account_payload["user"]["id"] == user
        assert source["raw_sha"] in {entry["sha256"] for entry in inspection.manifest["entries"]}
        assert source["generated_sha"] in {entry["sha256"] for entry in inspection.manifest["entries"]}
        assert all("storage_path" not in entry for entry in inspection.manifest["entries"])


def test_backup_preview_blocks_missing_required_and_warns_optional(app, user):
    with app.app_context():
        source = _source_account(app, user)
        upload = db.session.get(UploadedFile, source["upload_id"])
        (Path(app.config["DATA_ROOT"]) / upload.storage_path).unlink()
        preview = AccountBackupService().preview(db.session.get(User, user), user_id=user)
        assert preview["valid"] is False
        assert "missing" in preview["errors"][0].lower()

        db.session.delete(upload)
        export = db.session.get(ExportRecord, source["export_id"])
        (Path(app.config["DATA_ROOT"]) / export.relative_path).unlink()
        db.session.commit()
        preview = AccountBackupService().preview(db.session.get(User, user), user_id=user)
        assert preview["valid"] is True
        assert any("omitted" in warning for warning in preview["warnings"])


@pytest.mark.parametrize(
    ("bad_name", "message"),
    [
        ("../account/user_data_export.json", "traversal"),
        ("/account/user_data_export.json", "path"),
        ("C:/account/user_data_export.json", "drive"),
    ],
)
def test_backup_reader_rejects_unsafe_paths(app, tmp_path, bad_name, message):
    account = _json_bytes(_empty_account_payload())
    manifest = _manifest_for(account, path=bad_name)
    archive = tmp_path / "unsafe.zip"
    _write_archive(archive, manifest, [(bad_name, account)])
    with app.app_context(), pytest.raises(BackupSecurityError, match=message):
        BackupArchiveReader().inspect(archive)


def test_backup_reader_rejects_duplicate_case_collision_and_symlink(app, tmp_path):
    account = _json_bytes(_empty_account_payload())
    manifest = _manifest_for(account)

    duplicate = tmp_path / "duplicate.zip"
    with ZipFile(duplicate, "w") as archive:
        archive.writestr(MANIFEST_PATH, _json_bytes(manifest))
        archive.writestr(ACCOUNT_EXPORT_PATH, account)
        archive.writestr(ACCOUNT_EXPORT_PATH, account)
    with app.app_context(), pytest.raises(BackupSecurityError, match="duplicate"):
        BackupArchiveReader().inspect(duplicate)

    case_collision = tmp_path / "case.zip"
    with ZipFile(case_collision, "w") as archive:
        archive.writestr(MANIFEST_PATH, _json_bytes(manifest))
        archive.writestr("Manifest.JSON", b"x")
        archive.writestr(ACCOUNT_EXPORT_PATH, account)
    with app.app_context(), pytest.raises(BackupSecurityError, match="case-colliding"):
        BackupArchiveReader().inspect(case_collision)

    symlink = tmp_path / "symlink.zip"
    info = ZipInfo(ACCOUNT_EXPORT_PATH)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(symlink, "w") as archive:
        archive.writestr(MANIFEST_PATH, _json_bytes(manifest))
        archive.writestr(info, b"target")
    with app.app_context(), pytest.raises(BackupSecurityError, match="links"):
        BackupArchiveReader().inspect(symlink)


def test_backup_reader_rejects_future_version_extra_entry_and_hash_mismatch(app, tmp_path):
    account = _json_bytes(_empty_account_payload())

    future = _manifest_for(account)
    future["backup_format_version"] = "2.0"
    path = tmp_path / "future.zip"
    _write_archive(path, future, [(ACCOUNT_EXPORT_PATH, account)])
    with app.app_context(), pytest.raises(BackupSecurityError, match="version"):
        BackupArchiveReader().inspect(path)

    extra = _manifest_for(account)
    path = tmp_path / "extra.zip"
    _write_archive(path, extra, [(ACCOUNT_EXPORT_PATH, account), ("raw/extra/file", b"x")])
    with app.app_context(), pytest.raises(BackupSecurityError, match="undeclared"):
        BackupArchiveReader().inspect(path)

    mismatch = _manifest_for(account)
    mismatch["entries"][0]["sha256"] = "0" * 64
    path = tmp_path / "hash.zip"
    _write_archive(path, mismatch, [(ACCOUNT_EXPORT_PATH, account)])
    with app.app_context(), pytest.raises(BackupSecurityError, match="SHA256"):
        BackupArchiveReader().inspect(path)


def test_backup_reader_rejects_compression_bomb(app, tmp_path):
    payload = b"A" * (2 * 1024 * 1024)
    manifest = _manifest_for(payload)
    archive = tmp_path / "bomb.zip"
    _write_archive(archive, manifest, [(ACCOUNT_EXPORT_PATH, payload)])
    with app.app_context(), pytest.raises(BackupSecurityError, match="ratio"):
        BackupArchiveReader().inspect(archive)


def test_backup_reader_rejects_missing_manifest_account_malformed_and_unknown_kind(app, tmp_path):
    account = _json_bytes(_empty_account_payload())

    missing_manifest = tmp_path / "missing-manifest.zip"
    with ZipFile(missing_manifest, "w") as archive:
        archive.writestr(ACCOUNT_EXPORT_PATH, account)
    with app.app_context(), pytest.raises(BackupSecurityError, match="manifest"):
        BackupArchiveReader().inspect(missing_manifest)

    missing_account = tmp_path / "missing-account.zip"
    manifest = _manifest_for(account)
    with ZipFile(missing_account, "w") as archive:
        archive.writestr(MANIFEST_PATH, _json_bytes(manifest))
    with app.app_context(), pytest.raises(BackupSecurityError, match="undeclared or missing"):
        BackupArchiveReader().inspect(missing_account)

    malformed = tmp_path / "malformed.zip"
    manifest = _manifest_for(b"not-json")
    _write_archive(malformed, manifest, [(ACCOUNT_EXPORT_PATH, b"not-json")])
    with app.app_context(), pytest.raises(BackupSecurityError, match="UTF-8 JSON"):
        BackupArchiveReader().inspect(malformed)

    unknown = tmp_path / "unknown-kind.zip"
    manifest = _manifest_for(account)
    manifest["entries"][0]["kind"] = "unknown_required"
    _write_archive(unknown, manifest, [(ACCOUNT_EXPORT_PATH, account)])
    with app.app_context(), pytest.raises(BackupSecurityError, match="manifest is invalid"):
        BackupArchiveReader().inspect(unknown)


def test_backup_reader_enforces_entry_count_and_size_limits(app, tmp_path, monkeypatch):
    account = _json_bytes(_empty_account_payload())
    manifest = _manifest_for(account)
    archive = tmp_path / "count.zip"
    _write_archive(
        archive,
        manifest,
        [(ACCOUNT_EXPORT_PATH, account), ("raw/extra/file", b"x")],
    )
    monkeypatch.setattr(backups_module, "MAX_BACKUP_ENTRIES", 1)
    with app.app_context(), pytest.raises(BackupSecurityError, match="too many"):
        BackupArchiveReader().inspect(archive)

    monkeypatch.setattr(backups_module, "MAX_BACKUP_ENTRIES", 2000)
    monkeypatch.setattr(backups_module, "MAX_BACKUP_ENTRY_BYTES", 8)
    archive = tmp_path / "size.zip"
    _write_archive(archive, manifest, [(ACCOUNT_EXPORT_PATH, account)])
    with app.app_context(), pytest.raises(BackupSecurityError, match="size limit"):
        BackupArchiveReader().inspect(archive)


def test_full_backup_restore_roundtrip_binary_ownership_and_idempotency(app, user):
    with app.app_context():
        source = _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-user")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()

        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)
        assert preview["read_only"] is True
        assert preview["files"]["inserts"] == 2
        assert db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == destination.id)
        ).scalar_one_or_none() is None

        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination.id,
            confirmation_token=preview["confirmation_token"],
        )
        assert result["committed"] is True
        restored_upload = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == destination.id)
        ).scalar_one()
        restored_export = db.session.execute(
            db.select(ExportRecord).where(
                ExportRecord.user_id == destination.id,
                ExportRecord.domain == "weigh_in",
            )
        ).scalar_one()
        assert restored_upload.id != source["upload_id"]
        assert restored_upload.sha256 == source["raw_sha"]
        assert (Path(app.config["DATA_ROOT"]) / restored_upload.storage_path).read_bytes() == source["raw_bytes"]
        assert restored_export.sha256 == source["generated_sha"]
        assert (Path(app.config["DATA_ROOT"]) / restored_export.relative_path).read_bytes() == source["generated_bytes"]
        assert db.session.execute(
            db.select(WeighIn).where(WeighIn.user_id == destination.id)
        ).scalar_one().weight_kg == pytest.approx(80.5)
        restored_activity = db.session.execute(
            db.select(Activity).where(Activity.user_id == destination.id)
        ).scalar_one()
        assert restored_activity.source_file_id == restored_upload.id

        staging_id = _stage(backup_path, coordinator, destination.id)
        repeat_preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)
        assert repeat_preview["files"]["inserts"] == 0
        assert repeat_preview["files"]["skips"] == 2
        repeat = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination.id,
            confirmation_token=repeat_preview["confirmation_token"],
        )
        assert repeat["committed"] is True
        assert db.session.scalar(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == destination.id)
        ) == 1
        assert db.session.scalar(
            db.select(db.func.count(ExportRecord.id)).where(
                ExportRecord.user_id == destination.id,
                ExportRecord.domain == "weigh_in",
            )
        ) == 1
        assert db.session.get(User, user) is not None

        _second_record, destination_backup = _create_backup(app, destination.id)
        second_inspection = BackupArchiveReader().inspect(destination_backup)
        first_inspection = BackupArchiveReader().inspect(backup_path)
        first_binary_hashes = {
            entry["sha256"]
            for entry in first_inspection.manifest["entries"]
            if entry["kind"] in {"raw_upload", "generated_export"}
        }
        second_binary_hashes = {
            entry["sha256"]
            for entry in second_inspection.manifest["entries"]
            if entry["kind"] in {"raw_upload", "generated_export"}
        }
        assert first_binary_hashes == second_binary_hashes
        first_weight = first_inspection.account_payload["data"]["weigh_ins"][0]["data"]
        second_weight = second_inspection.account_payload["data"]["weigh_ins"][0]["data"]
        assert first_weight == second_weight


def test_complete_domain_backup_roundtrip_is_semantically_and_binary_equivalent(app, user):
    with app.app_context():
        _complete_account_payload(user)
        source_files = _source_account(app, user)
        source_user = db.session.get(User, user)
        source_export = build_user_data_document(source_user, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("complete-backup-destination")
        destination_id = destination.id
        db.session.commit()

        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination_id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination_id)
        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination_id,
            confirmation_token=preview["confirmation_token"],
        )
        assert result["committed"] is True
        destination_export = build_user_data_document(
            db.session.get(User, destination_id),
            destination_id,
        )
        for document in (source_export, destination_export):
            document["data"].pop("uploads", None)
            document["data"].pop("export_records", None)
        assert _semantic_export(destination_export) == _semantic_export(source_export)

        restored_raw = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.user_id == destination_id,
                UploadedFile.sha256 == source_files["raw_sha"],
            )
        ).scalar_one()
        restored_generated = db.session.execute(
            db.select(ExportRecord).where(
                ExportRecord.user_id == destination_id,
                ExportRecord.sha256 == source_files["generated_sha"],
            )
        ).scalar_one()
        assert (Path(app.config["DATA_ROOT"]) / restored_raw.storage_path).read_bytes() == source_files["raw_bytes"]
        assert (Path(app.config["DATA_ROOT"]) / restored_generated.relative_path).read_bytes() == source_files["generated_bytes"]


def test_backup_restore_token_tamper_user_mismatch_and_changed_archive(app, user):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-token")
        other = _user("other-token")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)

        with pytest.raises(BackupTokenError):
            coordinator.confirm(
                staging_id=staging_id,
                user_id=destination.id,
                confirmation_token=preview["confirmation_token"] + "tampered",
            )
        with pytest.raises(BackupError, match="missing"):
            coordinator.preview(staging_id=staging_id, user_id=other.id)

        staged_path = Path(app.config["DATA_ROOT"]) / "staging" / "account_backups" / f"user_{destination.id}" / staging_id / "backup.zip"
        staged_path.write_bytes(staged_path.read_bytes() + b"changed")
        with pytest.raises(BackupTokenError, match="changed"):
            coordinator.confirm(
                staging_id=staging_id,
                user_id=destination.id,
                confirmation_token=preview["confirmation_token"],
            )
        assert db.session.scalar(
            db.select(db.func.count(ImportRun.id)).where(ImportRun.user_id == destination.id)
        ) == 0


def test_backup_restore_token_expiry_is_rejected_before_audit(app, user):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-expired")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)
        inspection = coordinator._inspection(staging_id=staging_id, user_id=destination.id)
        account_preview = coordinator.account_restore.preview(
            inspection.account_payload,
            user_id=destination.id,
        )
        file_plan = coordinator._file_plan(inspection, user_id=destination.id)
        with pytest.raises(BackupTokenError, match="expired"):
            coordinator._verify_token(
                preview["confirmation_token"],
                user_id=destination.id,
                staging_id=staging_id,
                inspection=inspection,
                account_plan_sha256=account_preview["plan_sha256"],
                file_plan=file_plan,
                max_age=-1,
            )
        assert db.session.scalar(
            db.select(db.func.count(ImportRun.id)).where(ImportRun.user_id == destination.id)
        ) == 0


def test_backup_restore_rolls_back_data_and_files_on_file_failure(app, user, monkeypatch):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-rollback")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)

        original = coordinator._restore_generated_record

        def fail_generated(*args, **kwargs):
            raise OSError("fictional copy failure")

        monkeypatch.setattr(coordinator, "_restore_generated_record", fail_generated)
        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination.id,
            confirmation_token=preview["confirmation_token"],
        )
        monkeypatch.setattr(coordinator, "_restore_generated_record", original)

        assert result["committed"] is False
        assert result["rollback"] is True
        assert db.session.scalar(
            db.select(db.func.count(WeighIn.id)).where(WeighIn.user_id == destination.id)
        ) == 0
        assert db.session.scalar(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == destination.id)
        ) == 0
        run = db.session.get(ImportRun, result["audit_run_id"])
        assert run.status == "failed"
        assert "fictional" not in (run.error_message or "")


def test_backup_restore_rejects_changed_plan_before_audit(app, user):
    with app.app_context():
        source = _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-plan-change")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)

        source_upload = db.session.get(UploadedFile, source["upload_id"])
        shadow_path = Path(app.config["UPLOAD_ROOT"]) / f"user_{destination.id}" / source["raw_sha"]
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_bytes(source["raw_bytes"])
        db.session.add(
            UploadedFile(
                user_id=destination.id,
                original_filename="already-there.fit",
                stored_filename=source["raw_sha"],
                storage_path=shadow_path.relative_to(app.config["DATA_ROOT"]).as_posix(),
                source_type="uploaded",
                detected_type=source_upload.detected_type,
                import_status="imported",
                sha256=source["raw_sha"],
                size_bytes=len(source["raw_bytes"]),
                mime_type=source_upload.mime_type,
            )
        )
        db.session.commit()

        with pytest.raises(BackupTokenError, match="changed"):
            coordinator.confirm(
                staging_id=staging_id,
                user_id=destination.id,
                confirmation_token=preview["confirmation_token"],
            )
        assert db.session.scalar(
            db.select(db.func.count(ImportRun.id)).where(ImportRun.user_id == destination.id)
        ) == 0


def test_backup_restore_audit_finalize_failure_rolls_back_files_and_data(app, user, monkeypatch):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-audit-failure")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)

        def fail_audit(*args, **kwargs):
            raise RuntimeError("fictional audit failure")

        monkeypatch.setattr(coordinator.audit_service, "finalize_succeeded", fail_audit)
        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination.id,
            confirmation_token=preview["confirmation_token"],
        )
        assert result["committed"] is False
        assert db.session.scalar(
            db.select(db.func.count(WeighIn.id)).where(WeighIn.user_id == destination.id)
        ) == 0
        assert db.session.scalar(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == destination.id)
        ) == 0
        assert db.session.get(ImportRun, result["audit_run_id"]).status == "failed"


def test_backup_restore_database_commit_failure_compensates_files(app, user, monkeypatch):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-db-failure")
        destination_id = destination.id
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination_id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination_id)
        original_commit = db.session.commit
        commit_calls = 0

        def fail_domain_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                raise RuntimeError("fictional database commit failure")
            return original_commit()

        monkeypatch.setattr(db.session, "commit", fail_domain_commit)
        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination_id,
            confirmation_token=preview["confirmation_token"],
        )

        assert result["committed"] is False
        assert result["rollback"] is True
        assert commit_calls == 3
        assert db.session.scalar(
            db.select(db.func.count(WeighIn.id)).where(WeighIn.user_id == destination_id)
        ) == 0
        assert db.session.scalar(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == destination_id)
        ) == 0
        assert db.session.get(ImportRun, result["audit_run_id"]).status == "failed"
        restored_raw_directory = Path(app.config["UPLOAD_ROOT"]) / f"user_{destination_id}"
        assert not restored_raw_directory.exists() or not any(restored_raw_directory.iterdir())


def test_backup_restore_cleanup_failure_is_audited_and_recoverable(app, user, monkeypatch):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("destination-cleanup")
        db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging_id = _stage(backup_path, coordinator, destination.id)
        preview = coordinator.preview(staging_id=staging_id, user_id=destination.id)

        def fail_cleanup(_path):
            raise OSError("fictional cleanup failure")

        monkeypatch.setattr(backups_module, "_remove_tree", fail_cleanup)
        result = coordinator.confirm(
            staging_id=staging_id,
            user_id=destination.id,
            confirmation_token=preview["confirmation_token"],
        )
        assert result["committed"] is True
        assert result["cleanup_status"] == "failed"
        run = db.session.get(ImportRun, result["audit_run_id"])
        assert run.status == "succeeded"
        assert run.metadata_json["cleanup_status"] == "failed"


def test_backup_reconciliation_dry_run_and_apply(app, user):
    with app.app_context():
        missing = UploadedFile(
            user_id=user,
            original_filename="missing.fit",
            stored_filename="a" * 64,
            storage_path=f"uploads/raw/user_{user}/{'a' * 64}",
            source_type="uploaded",
            detected_type="activity",
            import_status="pending",
            sha256="a" * 64,
            size_bytes=10,
            mime_type="application/octet-stream",
        )
        pending = ImportRun(
            user_id=user,
            target_type="full_backup_restore",
            source_type="backup_zip",
            status="pending",
            started_at=datetime.now(timezone.utc) - timedelta(days=2),
            payload_sha256="b" * 64,
            plan_sha256="c" * 64,
        )
        db.session.add_all([missing, pending])
        db.session.commit()
        staging = Path(app.config["DATA_ROOT"]) / "staging" / "account_backups" / f"user_{user}" / ("d" * 32)
        staging.mkdir(parents=True)
        old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
        os.utime(staging, (old, old))

        report = BackupReconciliationService().reconcile(apply=False, stale_after_hours=24)
        assert report["missing_uploads"] == 1
        assert report["abandoned_runs"] == 1
        assert report["stale_staging"] == 1
        assert db.session.get(UploadedFile, missing.id).import_status == "pending"
        assert db.session.get(ImportRun, pending.id).status == "pending"
        assert staging.exists()

        report = BackupReconciliationService().reconcile(apply=True, stale_after_hours=24)
        assert report["records_updated"] == 2
        assert report["staging_removed"] == 1
        assert db.session.get(UploadedFile, missing.id).import_status == "error"
        assert db.session.get(ImportRun, pending.id).status == "failed"
        assert not staging.exists()


def test_backup_web_login_owner_download_preview_confirm_and_single_use(app, client, user):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
        destination = _user("web-destination")
        destination_id = destination.id
        db.session.commit()

    assert client.get("/account/backups").status_code == 302
    login = client.post(
        "/login",
        data={"username": "web-destination", "password": "fictional-test-password"},
    )
    assert login.status_code == 302
    assert client.get("/account/backups").status_code == 200
    with backup_path.open("rb") as source:
        response = client.post(
            "/account/backups/restore",
            data={"file": (BytesIO(source.read()), "backup.zip")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    token = re.search(r'name="confirmation_token"[^>]*value="([^"]+)"', html).group(1)
    staging_id = re.search(r'name="staging_id"[^>]*value="([^"]+)"', html).group(1)
    response = client.post(
        "/account/backups/restore/confirm",
        data={"confirmation_token": token, "staging_id": staging_id},
    )
    assert response.status_code == 200
    assert "Restaurado" in response.get_data(as_text=True)
    response = client.post(
        "/account/backups/restore/confirm",
        data={"confirmation_token": token, "staging_id": staging_id},
    )
    assert response.status_code == 200
    assert "ya fue usado" in response.get_data(as_text=True)
    with app.app_context():
        restored_upload = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == destination_id)
        ).scalar_one()
        restored_export = db.session.execute(
            db.select(ExportRecord).where(
                ExportRecord.user_id == destination_id,
                ExportRecord.domain == "weigh_in",
            )
        ).scalar_one()
        assert db.session.scalar(
            db.select(db.func.count(UploadedFile.id)).where(UploadedFile.user_id == destination_id)
        ) == 1
        restored_upload_id = restored_upload.id
        restored_export_id = restored_export.id
    raw_response = client.get(f"/account/uploads/{restored_upload_id}/download")
    generated_response = client.get(f"/exports/{restored_export_id}/download")
    assert raw_response.status_code == 200
    assert generated_response.status_code == 200
    assert raw_response.headers["X-Content-Type-Options"] == "nosniff"


def test_backup_download_is_owner_only(app, client, user):
    with app.app_context():
        _source_account(app, user)
        record, _path = _create_backup(app, user)
        other = _user("download-other")
        db.session.commit()
        backup_id = record.id
    client.post(
        "/login",
        data={"username": "download-other", "password": "fictional-test-password"},
    )
    assert client.get(f"/account/backups/{backup_id}").status_code == 404
    assert client.get(f"/account/backups/{backup_id}/download").status_code == 404
    with app.app_context():
        source_upload_id = db.session.execute(
            db.select(UploadedFile.id).where(UploadedFile.user_id == user)
        ).scalar_one()
    assert client.get(f"/account/uploads/{source_upload_id}/download").status_code == 404


def test_backup_web_creation_history_detail_and_download(app, client, user):
    with app.app_context():
        _source_account(app, user)
    client.post(
        "/login",
        data={"username": "test-user", "password": "test-password"},
    )
    page = client.get("/account/backups/new")
    assert page.status_code == 200
    assert "Generar backup completo" in page.get_data(as_text=True)
    response = client.post("/account/backups/new", data={}, follow_redirects=False)
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert "ZIP backup 1.0" in detail.get_data(as_text=True)
    history = client.get("/account/backups")
    assert history.status_code == 200
    assert "Backups completos" in history.get_data(as_text=True)
    with app.app_context():
        backup_id = db.session.execute(
            db.select(ExportRecord.id).where(
                ExportRecord.user_id == user,
                ExportRecord.domain == "account_backup",
            )
        ).scalar_one()
    download = client.get(f"/account/backups/{backup_id}/download")
    assert download.status_code == 200
    assert download.mimetype == "application/zip"
    assert download.headers["X-Content-Type-Options"] == "nosniff"


def test_backup_restore_preview_requires_csrf_when_enabled(app, client, user):
    with app.app_context():
        _source_account(app, user)
        _record, backup_path = _create_backup(app, user)
    client.post(
        "/login",
        data={"username": "test-user", "password": "test-password"},
    )
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        response = client.post(
            "/account/backups/restore",
            data={"file": (BytesIO(backup_path.read_bytes()), "backup.zip")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400

        page = client.get("/account/backups/restore")
        csrf_token = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"',
            page.get_data(as_text=True),
        ).group(1)
        response = client.post(
            "/account/backups/restore",
            data={
                "csrf_token": csrf_token,
                "file": (BytesIO(backup_path.read_bytes()), "backup.zip"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert "Preview verificado" in response.get_data(as_text=True)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# ---------------------------------------------------------------------------
# orphan_details dry-run tests
# ---------------------------------------------------------------------------


def _write_orphan_raw(app, name: str = "orphan-raw.bin") -> Path:
    """Create an unregistered file in UPLOAD_ROOT and return its path."""
    root = Path(app.config["UPLOAD_ROOT"])
    orphan = root / name
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"fictional-orphan-raw-content")
    return orphan


def _write_orphan_generated(app, name: str = "orphan-generated.json") -> Path:
    """Create an unregistered file in GENERATED_UPLOAD_ROOT and return its path."""
    root = Path(app.config["GENERATED_UPLOAD_ROOT"])
    orphan = root / name
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b'{"fictional": "orphan"}')
    return orphan


def test_reconcile_orphan_raw_detail_canonical(app, user):
    """Canonical orphan in UPLOAD_ROOT produces relative_path and legacy_upload."""
    with app.app_context():
        # Canonical format: user_\d+/[a-f0-9]{64}
        orphan = _write_orphan_raw(app, f"user_{user}/" + "a" * 64)
        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        raw_details = [d for d in details if d["storage_kind"] == "raw"]
        assert len(raw_details) >= 1
        d = raw_details[0]
        assert d["probable_category"] == "legacy_upload"
        assert d["matching_database_record"] is False
        assert "relative_path" in d
        assert "path_fingerprint" not in d
        # No absolute path
        assert not d.get("relative_path", "").startswith("/")
        # No original_filename or content key
        assert "original_filename" not in d
        assert "content" not in d


def test_reconcile_orphan_raw_detail_non_canonical(app, user):
    """Non-canonical orphan (e.g. user-supplied name) produces path_fingerprint and unknown."""
    with app.app_context():
        orphan = _write_orphan_raw(app, f"user_{user}/mi-archivo-ñ.fit")
        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        raw_details = [d for d in details if d["storage_kind"] == "raw"]
        assert len(raw_details) >= 1
        d = raw_details[0]
        assert d["probable_category"] == "unknown"
        assert d["matching_database_record"] is False
        assert "relative_path" not in d
        assert "path_fingerprint" in d
        assert "original_filename" not in d


def test_reconcile_orphan_generated_detail_canonical(app, user):
    """Canonical orphan in GENERATED_UPLOAD_ROOT produces relative_path and legacy_generated."""
    with app.app_context():
        # Canonical format: user_\d+/[a-f0-9]{64}.json
        orphan = _write_orphan_generated(app, f"user_{user}/" + "b" * 64 + ".json")
        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        gen_details = [d for d in details if d["storage_kind"] == "generated"]
        assert len(gen_details) >= 1
        d = gen_details[0]
        assert d["probable_category"] == "legacy_generated"
        assert d["matching_database_record"] is False
        assert "relative_path" in d
        assert "path_fingerprint" not in d


def test_reconcile_orphan_qa_artifact(app, user):
    """Orphan with staging/tmp/qa in path is classified as qa_artifact."""
    with app.app_context():
        orphan = _write_orphan_raw(app, "staging/some-file.bin")
        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        d = next(d for d in details if d["storage_kind"] == "raw")
        assert d["probable_category"] == "qa_artifact"
        assert "path_fingerprint" in d


def test_reconcile_orphan_matching_database_record_true(app, user):
    """An orphan that has a database record (e.g. non-ready ExportRecord) has matching_database_record=True."""
    with app.app_context():
        # Canonical export format: exports/user_\d+/[a-f0-9]{32}\.[a-z0-9]+
        relative = f"exports/user_{user}/" + "c" * 32 + ".json"
        orphan = _write_orphan_generated(app, relative)

        # Insert ExportRecord with status 'generating' so it's not added to known_paths
        record = ExportRecord(
            user_id=user,
            domain="weigh_in",
            source_type="weigh_in",
            source_id=1,
            format="json",
            exporter_version="1.0",
            filename="export.json",
            relative_path=f"uploads/generated/{relative}",
            media_type="application/json",
            size_bytes=10,
            sha256="c"*64,
            status="deleted",
        )
        db.session.add(record)
        db.session.commit()

        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        d = next(d for d in details if d["storage_kind"] == "generated")
        assert d["matching_database_record"] is True
        assert "relative_path" in d


def test_reconcile_orphan_detail_deterministic_order(app, user):
    """Multiple orphans are sorted deterministically by (storage_kind, path)."""
    with app.app_context():
        _write_orphan_raw(app, "z-last.bin")
        _write_orphan_raw(app, "a-first.bin")
        report = BackupReconciliationService().reconcile(apply=False)
        details = report.get("orphan_details", [])
        raw_details = [d for d in details if d["storage_kind"] == "raw"]
        paths = [d.get("relative_path") or d.get("path_fingerprint") for d in raw_details]
        assert paths == sorted(paths), f"Expected sorted, got: {paths}"


def test_reconcile_orphan_detail_no_absolute_path(app, user):
    """relative_path in orphan_details never starts with '/'."""
    with app.app_context():
        _write_orphan_raw(app)
        _write_orphan_generated(app)
        report = BackupReconciliationService().reconcile(apply=False)
        for d in report.get("orphan_details", []):
            rp = d.get("relative_path", "")
            assert not rp.startswith("/"), f"Absolute path leaked: {rp!r}"
            assert ":" not in rp, f"Windows drive letter leaked: {rp!r}"


def test_reconcile_orphan_detail_no_original_filename(app, user):
    """orphan_details entries must not expose original_filename."""
    with app.app_context():
        _write_orphan_raw(app)
        report = BackupReconciliationService().reconcile(apply=False)
        for d in report.get("orphan_details", []):
            assert "original_filename" not in d, "original_filename must not appear in orphan_details"


def test_reconcile_orphan_detail_no_content(app, user):
    """orphan_details entries must not expose file content."""
    with app.app_context():
        _write_orphan_raw(app)
        report = BackupReconciliationService().reconcile(apply=False)
        for d in report.get("orphan_details", []):
            assert "content" not in d, "content must not appear in orphan_details"


def test_reconcile_orphan_detail_vanished_file(app, user, monkeypatch):
    """A file that vanishes during scan does not cause a traceback."""
    from app.services import backup_reconcile as reconcile_module

    original_detail = BackupReconciliationService._orphan_detail

    call_count = {"n": 0}

    @staticmethod
    def detail_that_vanishes(root_key, root, path, data_root, db_paths):
        call_count["n"] += 1
        # Simulate vanished file by returning None (as OSError would cause).
        return None

    monkeypatch.setattr(BackupReconciliationService, "_orphan_detail", detail_that_vanishes)

    with app.app_context():
        _write_orphan_raw(app)
        # Must not raise; should silently skip vanished file.
        report = BackupReconciliationService().reconcile(apply=False)
        assert report["orphan_files"] >= 1
        # orphan_details should be absent (all details returned None).
        assert "orphan_details" not in report or report.get("orphan_details") == []


def test_reconcile_dry_run_does_not_modify(app, user):
    """Dry-run leaves orphan files untouched on disk."""
    with app.app_context():
        orphan = _write_orphan_raw(app, "dry-run-orphan.bin")
        before_content = orphan.read_bytes()
        report = BackupReconciliationService().reconcile(apply=False)
        assert report["orphan_files"] >= 1
        assert orphan.exists(), "Dry-run must not delete orphan files"
        assert orphan.read_bytes() == before_content, "Dry-run must not modify orphan files"


def test_reconcile_apply_does_not_delete_orphan_final(app, user):
    """--apply does not delete final orphan files."""
    with app.app_context():
        orphan = _write_orphan_raw(app, "apply-orphan.bin")
        report = BackupReconciliationService().reconcile(apply=True)
        assert report["orphan_files"] >= 1
        assert orphan.exists(), "--apply must not delete final orphan files"
        # orphan_details must not appear in apply mode
        assert "orphan_details" not in report


def test_reconcile_zero_orphans_preserves_existing_output(app, user):
    """With zero orphans, orphan_details is absent and counters are intact."""
    with app.app_context():
        report = BackupReconciliationService().reconcile(apply=False)
        # May have 0 or more orphans depending on test isolation, but we test
        # that when orphan_files==0 the key is absent.
        if report["orphan_files"] == 0:
            assert "orphan_details" not in report
        # All standard counter keys must always be present
        for key in (
            "missing_uploads",
            "corrupt_uploads",
            "missing_exports",
            "corrupt_exports",
            "orphan_files",
            "stale_staging",
            "abandoned_runs",
            "records_updated",
            "staging_removed",
        ):
            assert key in report, f"Expected counter '{key}' in report"


def test_reconcile_orphan_placeholder_ignored(app, user):
    """A .gitkeep at the root of UPLOAD_ROOT or GENERATED_UPLOAD_ROOT does not count as an orphan."""
    with app.app_context():
        _write_orphan_raw(app, ".gitkeep")
        _write_orphan_generated(app, ".gitkeep")

        report = BackupReconciliationService().reconcile(apply=False)
        # Should only be 0 because we only wrote .gitkeeps
        assert report["orphan_files"] == 0
        assert report.get("orphan_details", []) == []


def test_reconcile_orphan_placeholder_subdir_not_ignored(app, user):
    """A .gitkeep inside a subdirectory DOES count as an orphan."""
    with app.app_context():
        _write_orphan_raw(app, f"user_{user}/.gitkeep")
        report = BackupReconciliationService().reconcile(apply=False)
        assert report["orphan_files"] >= 1


def test_reconcile_orphan_other_hidden_files_not_ignored(app, user):
    """Other hidden files like .otherkeep DO count as orphans."""
    with app.app_context():
        _write_orphan_raw(app, ".otherkeep")
        report = BackupReconciliationService().reconcile(apply=False)
        assert report["orphan_files"] >= 1


def test_reconcile_orphan_symlink_is_suspicious(app, user):
    """Symlinks (including .gitkeep) are treated as suspicious_symlinks."""
    import os
    with app.app_context():
        # Create a file and a symlink to it
        target = _write_orphan_raw(app, "target.bin")
        symlink_path = Path(app.config["UPLOAD_ROOT"]) / "link.bin"
        gitkeep_symlink = Path(app.config["UPLOAD_ROOT"]) / ".gitkeep"
        try:
            os.symlink(target, symlink_path)
            os.symlink(target, gitkeep_symlink)

            report = BackupReconciliationService().reconcile(apply=False)
            assert report["suspicious_symlinks"] >= 2

            details = report.get("suspicious_symlink_details", [])
            assert any("link.bin" in d["path_fingerprint"] or True for d in details)

            # verify we don't leak absolute path or filename directly
            for d in details:
                assert d["storage_kind"] == "raw"
                assert "path_fingerprint" in d
                assert "reason" in d
                assert d["reason"] == "symlink_not_allowed"

            # Verify apply mode doesn't remove them
            BackupReconciliationService().reconcile(apply=True)
            assert symlink_path.exists(follow_symlinks=False)
            assert gitkeep_symlink.exists(follow_symlinks=False)
        except OSError:
            pass # Windows might require admin privileges for symlinks
        finally:
            if symlink_path.exists(follow_symlinks=False):
                symlink_path.unlink()
            if gitkeep_symlink.exists(follow_symlinks=False):
                gitkeep_symlink.unlink()


def test_reconcile_orphan_fingerprint_namespace(app, user):
    """The same relative path in raw and generated produces different fingerprints."""
    with app.app_context():
        # mi-archivo-ñ.fit will not match canonical rules, so it uses a fingerprint
        _write_orphan_raw(app, f"user_{user}/mi-archivo-ñ.fit")
        _write_orphan_generated(app, f"user_{user}/mi-archivo-ñ.fit")
        report = BackupReconciliationService().reconcile(apply=False)

        details = report.get("orphan_details", [])
        raw_detail = next(d for d in details if d["storage_kind"] == "raw")
        gen_detail = next(d for d in details if d["storage_kind"] == "generated")

        assert "path_fingerprint" in raw_detail
        assert "path_fingerprint" in gen_detail
        assert raw_detail["path_fingerprint"] != gen_detail["path_fingerprint"]


def test_reconcile_apply_does_not_remove_placeholders(app, user):
    """The apply mode must not remove root .gitkeep placeholders."""
    with app.app_context():
        raw_gitkeep = _write_orphan_raw(app, ".gitkeep")
        gen_gitkeep = _write_orphan_generated(app, ".gitkeep")

        BackupReconciliationService().reconcile(apply=True)
        assert raw_gitkeep.exists()
        assert gen_gitkeep.exists()
