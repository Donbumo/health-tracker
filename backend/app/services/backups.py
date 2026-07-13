from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
from typing import Any, BinaryIO
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Activity, ExportRecord, Route, UploadedFile, User
from app.services.account_restore import (
    AccountRestoreError,
    AccountRestoreService,
    AccountRestoreTokenError,
)
from app.services.exporters.user_data import build_user_data_document
from app.services.import_audit import ImportAuditService
from app.services.importers.standard_import_executor import canonical_sha256
from app.services.validation import JsonSchemaValidationError, validate_json_document


BACKUP_FORMAT_VERSION = "1.0"
BACKUP_SCHEMA_VERSION = "1.0"
BACKUP_EXPORTER_VERSION = "1.0"
BACKUP_DOMAIN = "account_backup"
BACKUP_RESTORE_TARGET = "full_backup_restore"
BACKUP_RESTORE_SOURCE = "backup_zip"
BACKUP_TOKEN_SALT = "full-backup-restore-v1"
BACKUP_TOKEN_VERSION = "1"
BACKUP_TOKEN_MAX_AGE_SECONDS = 15 * 60
ACCOUNT_EXPORT_PATH = "account/user_data_export.json"
MANIFEST_PATH = "manifest.json"

MAX_BACKUP_COMPRESSED_BYTES = 100 * 1024 * 1024
MAX_BACKUP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_BACKUP_ENTRY_BYTES = 100 * 1024 * 1024
MAX_BACKUP_ENTRIES = 2000
MAX_BACKUP_PATH_DEPTH = 6
MAX_BACKUP_COMPRESSION_RATIO = 100
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ACCOUNT_EXPORT_BYTES = 10 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024

_STAGING_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_.-]+$")
_UPLOAD_SOURCE_TYPES = {
    "uploaded",
    "manual_generated",
    "converted",
    "system_generated",
    "synced_from_device",
}
_UPLOAD_STATUSES = {"pending", "imported", "duplicate", "error"}


class BackupError(ValueError):
    pass


class BackupSecurityError(BackupError):
    pass


class BackupTokenError(BackupError):
    pass


@dataclass(frozen=True)
class BackupInspection:
    archive_path: Path
    backup_sha256: str
    manifest_sha256: str
    manifest: dict[str, Any]
    account_payload: dict[str, Any]
    entries_by_path: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _BackupSource:
    entry: dict[str, Any]
    path: Path | None
    content: bytes | None = None


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(STREAM_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_original_filename(value: str | None) -> str:
    name = (value or "file").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if character.isprintable()).strip()
    return (name or "file")[:255]


def _zip_name(value: str) -> str:
    safe = _safe_original_filename(value)
    safe = safe.replace("/", "_").replace("\\", "_")
    return safe or "file"


def _data_path(relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise BackupError("Stored file path is outside managed storage")
    root = Path(current_app.config["DATA_ROOT"]).resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise BackupError("Stored file path is outside managed storage") from error
    return candidate


def _relative_to_data(path: Path) -> str:
    root = Path(current_app.config["DATA_ROOT"]).resolve()
    return path.resolve().relative_to(root).as_posix()


def _staging_root() -> Path:
    root = Path(current_app.config["DATA_ROOT"]) / "staging" / "account_backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _staging_directory(user_id: int, staging_id: str) -> Path:
    if not _STAGING_ID.fullmatch(staging_id):
        raise BackupError("Invalid backup staging reference")
    root = _staging_root().resolve()
    candidate = (root / f"user_{user_id}" / staging_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise BackupError("Invalid backup staging reference") from error
    return candidate


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


class BackupArchiveReader:
    """Validate a backup archive without trusting names or extracting it."""

    def inspect(self, archive_path: Path) -> BackupInspection:
        archive_path = Path(archive_path)
        archive_sha256, compressed_size = _sha256_path(archive_path)
        if compressed_size > MAX_BACKUP_COMPRESSED_BYTES:
            raise BackupSecurityError("Backup exceeds the compressed size limit")
        try:
            with ZipFile(archive_path, "r") as archive:
                infos = archive.infolist()
                self._validate_infos(infos)
                by_name = {info.filename: info for info in infos}
                manifest_info = by_name.get(MANIFEST_PATH)
                if manifest_info is None:
                    raise BackupSecurityError("Backup manifest is missing")
                manifest_raw = self._read_limited(
                    archive,
                    manifest_info,
                    MAX_MANIFEST_BYTES,
                )
                manifest = self._decode_json(manifest_raw, "manifest")
                if manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
                    raise BackupSecurityError("Unsupported backup format version")
                try:
                    validate_json_document(manifest, "full_backup_manifest")
                except JsonSchemaValidationError as error:
                    raise BackupSecurityError("Backup manifest is invalid") from error

                entries = manifest["entries"]
                entries_by_path: dict[str, dict[str, Any]] = {}
                logical_ids: set[str] = set()
                for entry in entries:
                    path = entry["relative_path"]
                    self._validate_member_name(path)
                    folded_id = entry["logical_id"].casefold()
                    if folded_id in logical_ids:
                        raise BackupSecurityError("Backup contains duplicate logical IDs")
                    logical_ids.add(folded_id)
                    if path in entries_by_path:
                        raise BackupSecurityError("Backup manifest declares a path twice")
                    entries_by_path[path] = entry

                declared_names = {MANIFEST_PATH, *entries_by_path}
                if set(by_name) != declared_names:
                    raise BackupSecurityError("Backup contains undeclared or missing entries")
                account_entries = [
                    entry
                    for entry in entries
                    if entry["kind"] == "account_export"
                ]
                if len(account_entries) != 1:
                    raise BackupSecurityError("Backup must contain one account export")
                account_entry = account_entries[0]
                if account_entry["relative_path"] != ACCOUNT_EXPORT_PATH:
                    raise BackupSecurityError("Backup account export path is invalid")
                if manifest["account_export"] != ACCOUNT_EXPORT_PATH:
                    raise BackupSecurityError("Backup account export reference is invalid")

                total_bytes = 0
                for path, entry in entries_by_path.items():
                    info = by_name[path]
                    if info.file_size != entry["size_bytes"]:
                        raise BackupSecurityError("Backup entry size does not match manifest")
                    digest, actual_size = self._hash_member(archive, info)
                    if actual_size != entry["size_bytes"]:
                        raise BackupSecurityError("Backup entry size changed while reading")
                    if digest != entry["sha256"]:
                        raise BackupSecurityError("Backup entry SHA256 does not match manifest")
                    total_bytes += actual_size

                totals = manifest["totals"]
                if totals["entries"] != len(entries):
                    raise BackupSecurityError("Backup manifest entry total is inconsistent")
                if totals["uncompressed_bytes"] != total_bytes:
                    raise BackupSecurityError("Backup manifest byte total is inconsistent")
                if totals["raw_uploads"] != sum(
                    entry["kind"] == "raw_upload" for entry in entries
                ):
                    raise BackupSecurityError("Backup raw upload total is inconsistent")
                if totals["generated_exports"] != sum(
                    entry["kind"] == "generated_export" for entry in entries
                ):
                    raise BackupSecurityError("Backup generated export total is inconsistent")

                account_info = by_name[ACCOUNT_EXPORT_PATH]
                account_raw = self._read_limited(
                    archive,
                    account_info,
                    MAX_ACCOUNT_EXPORT_BYTES,
                )
                account_payload = self._decode_json(account_raw, "account export")
                try:
                    validate_json_document(account_payload, "user_data_export")
                except JsonSchemaValidationError as error:
                    raise BackupSecurityError("Backup account export is invalid") from error
        except BadZipFile as error:
            raise BackupSecurityError("File is not a valid ZIP backup") from error

        return BackupInspection(
            archive_path=archive_path,
            backup_sha256=archive_sha256,
            manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            manifest=manifest,
            account_payload=account_payload,
            entries_by_path=entries_by_path,
        )

    def extract_verified_entry(
        self,
        inspection: BackupInspection,
        entry: dict[str, Any],
        destination: Path,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with ZipFile(inspection.archive_path, "r") as archive:
                info = archive.getinfo(entry["relative_path"])
                with archive.open(info, "r") as source, destination.open("xb") as target:
                    while chunk := source.read(STREAM_CHUNK_BYTES):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if size != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
            destination.unlink(missing_ok=True)
            raise BackupSecurityError("Backup entry failed extraction verification")

    def _validate_infos(self, infos: list[ZipInfo]) -> None:
        if not infos:
            raise BackupSecurityError("Backup archive is empty")
        if len(infos) > MAX_BACKUP_ENTRIES + 1:
            raise BackupSecurityError("Backup contains too many entries")
        names: set[str] = set()
        folded_names: set[str] = set()
        total = 0
        for info in infos:
            self._validate_member_name(info.filename)
            if info.is_dir():
                raise BackupSecurityError("Backup may not contain directory entries")
            if info.flag_bits & 0x1:
                raise BackupSecurityError("Encrypted ZIP entries are not supported")
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type not in {0, stat.S_IFREG}:
                raise BackupSecurityError("Backup links and special files are not allowed")
            if info.filename in names:
                raise BackupSecurityError("Backup contains a duplicate path")
            folded = info.filename.casefold()
            if folded in folded_names:
                raise BackupSecurityError("Backup contains case-colliding paths")
            names.add(info.filename)
            folded_names.add(folded)
            if info.file_size > MAX_BACKUP_ENTRY_BYTES:
                raise BackupSecurityError("Backup entry exceeds the size limit")
            total += info.file_size
            if total > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise BackupSecurityError("Backup exceeds the uncompressed size limit")
            if (
                info.file_size > MAX_MANIFEST_BYTES
                and info.compress_size > 0
                and info.file_size / info.compress_size > MAX_BACKUP_COMPRESSION_RATIO
            ):
                raise BackupSecurityError("Backup compression ratio is unsafe")

    @staticmethod
    def _validate_member_name(name: str) -> None:
        if not name or len(name) > 512 or "\\" in name or "\x00" in name:
            raise BackupSecurityError("Backup contains an unsafe path")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise BackupSecurityError("Backup contains path traversal")
        if re.match(r"^[a-zA-Z]:", name):
            raise BackupSecurityError("Backup contains a drive-qualified path")
        if len(path.parts) > MAX_BACKUP_PATH_DEPTH:
            raise BackupSecurityError("Backup path is too deep")

    @staticmethod
    def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupSecurityError(f"Backup {label} is not valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise BackupSecurityError(f"Backup {label} must be a JSON object")
        return payload

    @staticmethod
    def _read_limited(archive: ZipFile, info: ZipInfo, limit: int) -> bytes:
        with archive.open(info, "r") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise BackupSecurityError("Backup JSON entry exceeds its size limit")
        return raw

    @staticmethod
    def _hash_member(archive: ZipFile, info: ZipInfo) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with archive.open(info, "r") as source:
            while chunk := source.read(STREAM_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size


class AccountBackupService:
    """Create complete account ZIP backups in managed generated storage."""

    def preview(self, user: User, *, user_id: int) -> dict[str, Any]:
        if user.id != user_id:
            raise BackupError("Backup account does not belong to this user")
        sources, warnings, errors = self._sources(user, user_id=user_id)
        entries = [source.entry for source in sources]
        return {
            "valid": not errors,
            "read_only": True,
            "data_sections": {
                key: len(value)
                for key, value in build_user_data_document(user, user_id)["data"].items()
                if isinstance(value, list)
            },
            "raw_uploads": sum(entry["kind"] == "raw_upload" for entry in entries),
            "generated_exports": sum(
                entry["kind"] == "generated_export" for entry in entries
            ),
            "entries": len(entries),
            "estimated_bytes": sum(entry["size_bytes"] for entry in entries),
            "warnings": warnings,
            "errors": errors,
        }

    def create(self, user: User, *, user_id: int) -> ExportRecord:
        if user.id != user_id:
            raise BackupError("Backup account does not belong to this user")
        sources, warnings, errors = self._sources(user, user_id=user_id)
        if errors:
            raise BackupError(errors[0])

        entries = [source.entry for source in sources]
        manifest = self._manifest(user_id=user_id, entries=entries, warnings=warnings)
        manifest_bytes = _json_bytes(manifest)
        output_directory = (
            Path(current_app.config["GENERATED_UPLOAD_ROOT"])
            / "backups"
            / f"user_{user_id}"
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temporary = output_directory / f".{token}.zip.creating"
        final = output_directory / f"health_tracker_backup_{token}.zip"
        try:
            with ZipFile(
                temporary,
                "x",
                compression=ZIP_STORED,
                allowZip64=True,
            ) as archive:
                archive.writestr(MANIFEST_PATH, manifest_bytes)
                for source in sources:
                    if source.content is not None:
                        archive.writestr(source.entry["relative_path"], source.content)
                    elif source.path is not None:
                        with source.path.open("rb") as input_stream, archive.open(
                            source.entry["relative_path"], "w"
                        ) as output_stream:
                            while chunk := input_stream.read(STREAM_CHUNK_BYTES):
                                output_stream.write(chunk)
            inspection = BackupArchiveReader().inspect(temporary)
            os.replace(temporary, final)
            backup_sha256, size_bytes = _sha256_path(final)
            record = ExportRecord(
                user_id=user_id,
                domain=BACKUP_DOMAIN,
                source_type="account",
                source_id=user_id,
                format="zip",
                exporter_version=BACKUP_EXPORTER_VERSION,
                filename=final.name,
                relative_path=_relative_to_data(final),
                media_type="application/zip",
                size_bytes=size_bytes,
                sha256=backup_sha256,
                status="ready",
                warnings_json=[
                    *warnings,
                    f"manifest_sha256:{inspection.manifest_sha256}",
                    f"entries:{inspection.manifest['totals']['entries']}",
                    f"raw_uploads:{inspection.manifest['totals']['raw_uploads']}",
                    f"generated_exports:{inspection.manifest['totals']['generated_exports']}",
                    f"uncompressed_bytes:{inspection.manifest['totals']['uncompressed_bytes']}",
                ],
            )
            db.session.add(record)
            db.session.commit()
            return record
        except Exception:
            db.session.rollback()
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise

    def list_records(self, *, user_id: int) -> list[ExportRecord]:
        return db.session.execute(
            db.select(ExportRecord)
            .where(
                ExportRecord.user_id == user_id,
                ExportRecord.domain == BACKUP_DOMAIN,
            )
            .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
        ).scalars().all()

    def get_record(self, *, user_id: int, backup_id: int) -> ExportRecord | None:
        return db.session.execute(
            db.select(ExportRecord).where(
                ExportRecord.id == backup_id,
                ExportRecord.user_id == user_id,
                ExportRecord.domain == BACKUP_DOMAIN,
            )
        ).scalar_one_or_none()

    def resolve_download(self, record: ExportRecord, *, user_id: int) -> Path:
        if record.user_id != user_id or record.domain != BACKUP_DOMAIN:
            raise BackupError("Backup does not belong to this user")
        if record.status != "ready":
            raise BackupError("Backup is not available")
        path = _data_path(record.relative_path)
        if not path.is_file():
            raise BackupError("Backup file is missing")
        digest, size = _sha256_path(path)
        if digest != record.sha256 or size != record.size_bytes:
            raise BackupError("Backup integrity check failed")
        return path
    def _sources(
        self,
        user: User,
        *,
        user_id: int,
    ) -> tuple[list[_BackupSource], list[str], list[str]]:
        warnings: list[str] = []
        errors: list[str] = []
        account_payload = build_user_data_document(user, user_id)
        account_bytes = _json_bytes(account_payload)
        if len(account_bytes) > MAX_ACCOUNT_EXPORT_BYTES:
            errors.append("Account export exceeds the 10 MB backup limit")
        sources: list[_BackupSource] = [
            _BackupSource(
                entry={
                    "logical_id": "account_export",
                    "kind": "account_export",
                    "relative_path": ACCOUNT_EXPORT_PATH,
                    "original_filename": "user_data_export.json",
                    "media_type": "application/json",
                    "size_bytes": len(account_bytes),
                    "sha256": hashlib.sha256(account_bytes).hexdigest(),
                    "source_record_type": None,
                    "source_record_id": None,
                    "source_file_id": None,
                    "required": True,
                    "metadata": {},
                },
                path=None,
                content=account_bytes,
            )
        ]

        uploads = db.session.execute(
            db.select(UploadedFile)
            .where(UploadedFile.user_id == user_id)
            .order_by(UploadedFile.id)
        ).scalars().all()
        for upload in uploads:
            logical_id = f"raw_{upload.id}"
            try:
                path = _data_path(upload.storage_path)
            except BackupError as error:
                errors.append(f"Required raw upload {upload.id} has an unsafe path: {error}")
                continue
            if not path.is_file():
                errors.append(f"Required raw upload {upload.id} is missing")
                continue
            digest, size = _sha256_path(path)
            if digest != upload.sha256 or size != upload.size_bytes:
                errors.append(f"Required raw upload {upload.id} failed integrity validation")
                continue
            sources.append(
                _BackupSource(
                    entry={
                        "logical_id": logical_id,
                        "kind": "raw_upload",
                        "relative_path": f"raw/{logical_id}/{_zip_name(upload.original_filename)}",
                        "original_filename": _safe_original_filename(upload.original_filename),
                        "media_type": _safe_media_type(upload.mime_type),
                        "size_bytes": size,
                        "sha256": digest,
                        "source_record_type": "uploaded_file",
                        "source_record_id": upload.id,
                        "source_file_id": logical_id,
                        "required": True,
                        "metadata": {
                            "source_type": _safe_token_value(upload.source_type, 64, "uploaded"),
                            "detected_type": _safe_token_value(upload.detected_type, 32, "unknown"),
                            "import_status": _safe_token_value(upload.import_status, 20, "pending"),
                        },
                    },
                    path=path,
                )
            )

        exports = db.session.execute(
            db.select(ExportRecord)
            .where(
                ExportRecord.user_id == user_id,
                ExportRecord.status == "ready",
                ExportRecord.domain != BACKUP_DOMAIN,
            )
            .order_by(ExportRecord.id)
        ).scalars().all()
        for record in exports:
            logical_id = f"generated_{record.id}"
            try:
                path = _data_path(record.relative_path)
            except BackupError:
                warnings.append(f"Optional generated export {record.id} has an unsafe path and was omitted")
                continue
            if not path.is_file():
                warnings.append(f"Optional generated export {record.id} is missing and was omitted")
                continue
            digest, size = _sha256_path(path)
            if digest != record.sha256 or size != record.size_bytes:
                warnings.append(f"Optional generated export {record.id} is corrupt and was omitted")
                continue
            sources.append(
                _BackupSource(
                    entry={
                        "logical_id": logical_id,
                        "kind": "generated_export",
                        "relative_path": f"generated/{logical_id}/{_zip_name(record.filename)}",
                        "original_filename": _safe_original_filename(record.filename),
                        "media_type": _safe_media_type(record.media_type),
                        "size_bytes": size,
                        "sha256": digest,
                        "source_record_type": _safe_token_value(record.domain, 64, None),
                        "source_record_id": record.source_id,
                        "source_file_id": None,
                        "required": False,
                        "metadata": {
                            "source_type": _safe_token_value(record.source_type, 64, "restored"),
                            "domain": _safe_token_value(record.domain, 64, "restored_export"),
                            "format": _safe_token_value(record.format, 32, "bin"),
                            "exporter_version": _safe_token_value(record.exporter_version, 20, "unknown"),
                            "status": "ready",
                        },
                    },
                    path=path,
                )
            )
        if sum(source.entry["size_bytes"] for source in sources) > (
            MAX_BACKUP_COMPRESSED_BYTES - MAX_MANIFEST_BYTES
        ):
            errors.append("Backup contents exceed the safe ZIP creation limit")
        return sources, warnings, errors

    @staticmethod
    def _manifest(
        *,
        user_id: int,
        entries: list[dict[str, Any]],
        warnings: list[str],
    ) -> dict[str, Any]:
        manifest = {
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": str(current_app.config.get("APP_VERSION") or "unknown")[:100],
            "source_account": {"source_user_id": user_id},
            "account_export": ACCOUNT_EXPORT_PATH,
            "entries": entries,
            "totals": {
                "entries": len(entries),
                "raw_uploads": sum(entry["kind"] == "raw_upload" for entry in entries),
                "generated_exports": sum(
                    entry["kind"] == "generated_export" for entry in entries
                ),
                "uncompressed_bytes": sum(entry["size_bytes"] for entry in entries),
            },
            "capabilities": [
                "account_data",
                "raw_uploads",
                "generated_exports",
                "sha256_verification",
            ],
            "unsupported": ["passwords", "sessions", "secrets", "encrypted_zip"],
            "warnings": warnings[:100],
        }
        validate_json_document(manifest, "full_backup_manifest")
        return manifest


def resolve_uploaded_download(record: UploadedFile, *, user_id: int) -> Path:
    if record.user_id != user_id:
        raise BackupError("Uploaded file does not belong to this user")
    path = _data_path(record.storage_path)
    if not path.is_file():
        raise BackupError("Uploaded file is missing")
    digest, size = _sha256_path(path)
    if digest != record.sha256 or size != record.size_bytes:
        raise BackupError("Uploaded file integrity check failed")
    return path


class BackupRestoreCoordinator:
    """Stage, preview and atomically coordinate account data plus file restore."""

    def __init__(
        self,
        *,
        reader: BackupArchiveReader | None = None,
        account_restore: AccountRestoreService | None = None,
        audit_service: ImportAuditService | None = None,
    ) -> None:
        self.reader = reader or BackupArchiveReader()
        self.account_restore = account_restore or AccountRestoreService()
        self.audit_service = audit_service or ImportAuditService()

    def stage_upload(self, storage: FileStorage, *, user_id: int) -> str:
        staging_id = uuid.uuid4().hex
        directory = _staging_directory(user_id, staging_id)
        directory.mkdir(parents=True, exist_ok=False)
        archive_path = directory / "backup.zip"
        size = 0
        try:
            with archive_path.open("xb") as target:
                while chunk := storage.stream.read(STREAM_CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_BACKUP_COMPRESSED_BYTES:
                        raise BackupSecurityError("Backup exceeds the compressed size limit")
                    target.write(chunk)
            self.reader.inspect(archive_path)
        except Exception:
            _remove_tree(directory)
            raise
        return staging_id

    def preview(self, *, staging_id: str, user_id: int) -> dict[str, Any]:
        inspection = self._inspection(staging_id=staging_id, user_id=user_id)
        account_preview = self.account_restore.preview(
            inspection.account_payload,
            user_id=user_id,
        )
        file_plan = self._file_plan(inspection, user_id=user_id)
        token = self._build_token(
            user_id=user_id,
            staging_id=staging_id,
            inspection=inspection,
            account_plan_sha256=account_preview["plan_sha256"],
            file_plan=file_plan,
        )
        warnings = [
            *inspection.manifest.get("warnings", []),
            *account_preview.get("warnings", []),
            *file_plan["warnings"],
        ]
        valid = (
            account_preview["plan"]["invalid"] == 0
            and account_preview["plan"]["conflicts"] == 0
            and file_plan["invalid"] == 0
            and file_plan["conflicts"] == 0
            and (account_preview["plan"]["valid"] > 0 or file_plan["valid"] > 0)
        )
        return {
            "valid": valid,
            "read_only": True,
            "writes_performed": False,
            "staging_id": staging_id,
            "backup_sha256": inspection.backup_sha256,
            "manifest_sha256": inspection.manifest_sha256,
            "manifest": {
                "created_at": inspection.manifest["created_at"],
                "app_version": inspection.manifest["app_version"],
                "totals": inspection.manifest["totals"],
                "capabilities": inspection.manifest["capabilities"],
                "unsupported": inspection.manifest["unsupported"],
            },
            "account": account_preview,
            "files": file_plan,
            "warnings": warnings,
            "confirmation_token": token,
        }

    def confirm(
        self,
        *,
        staging_id: str,
        user_id: int,
        confirmation_token: str,
    ) -> dict[str, Any]:
        inspection = self._inspection(staging_id=staging_id, user_id=user_id)
        account_preview = self.account_restore.preview(
            inspection.account_payload,
            user_id=user_id,
        )
        file_plan = self._file_plan(inspection, user_id=user_id)
        self._verify_token(
            confirmation_token,
            user_id=user_id,
            staging_id=staging_id,
            inspection=inspection,
            account_plan_sha256=account_preview["plan_sha256"],
            file_plan=file_plan,
        )
        if (
            account_preview["plan"]["invalid"]
            or account_preview["plan"]["conflicts"]
            or file_plan["invalid"]
            or file_plan["conflicts"]
            or (account_preview["plan"]["valid"] == 0 and file_plan["valid"] == 0)
        ):
            raise BackupError("Backup restore plan is blocked")

        summary = _combined_summary(account_preview["plan"], file_plan)
        metadata = {
            "route": "/account/backups/restore/confirm",
            "mode": "full_backup_restore",
            "contract_version": "full-backup-v1",
            "document_count": summary["total"],
            "backup_sha256": inspection.backup_sha256,
            "manifest_sha256": inspection.manifest_sha256,
            "file_count": file_plan["total"],
            "byte_count": file_plan["bytes"],
        }
        audit_run = self.audit_service.record_pending(
            user_id=user_id,
            target_type=BACKUP_RESTORE_TARGET,
            source_type=BACKUP_RESTORE_SOURCE,
            payload_sha256=inspection.backup_sha256,
            plan_sha256=canonical_sha256(
                {
                    "account": account_preview["plan_sha256"],
                    "files": self.file_plan_sha256(file_plan),
                }
            ),
            summary=summary,
            metadata=metadata,
        )

        moved_paths: list[Path] = []
        temporary_paths: list[Path] = []
        try:
            account_result = self.account_restore.apply_in_transaction(
                inspection.account_payload,
                user_id=user_id,
                expected_plan_sha256=account_preview["plan_sha256"],
            )
            file_result = self._restore_files(
                inspection,
                file_plan=file_plan,
                account_result=account_result,
                user_id=user_id,
                staging_id=staging_id,
                moved_paths=moved_paths,
                temporary_paths=temporary_paths,
            )
            result_summary = _combined_summary(account_result, file_result)
            self.audit_service.finalize_succeeded(audit_run, result_summary)
            db.session.commit()
        except Exception:
            db.session.rollback()
            for path in reversed(moved_paths):
                path.unlink(missing_ok=True)
            for path in temporary_paths:
                path.unlink(missing_ok=True)
            failed = {
                **summary,
                "committed": False,
                "rollback": True,
                "errors": ["Backup restore failed; no partial data was kept."],
            }
            run = self.audit_service.record_failed_existing(
                run_id=audit_run.id,
                summary=failed,
                error_message="Backup restore failed; no partial data was kept.",
                fallback={
                    "user_id": user_id,
                    "target_type": BACKUP_RESTORE_TARGET,
                    "source_type": BACKUP_RESTORE_SOURCE,
                    "payload_sha256": inspection.backup_sha256,
                    "plan_sha256": canonical_sha256(
                        {
                            "account": account_preview["plan_sha256"],
                            "files": self.file_plan_sha256(file_plan),
                        }
                    ),
                    "metadata": metadata,
                },
            )
            return {**failed, "audit_run_id": run.id}

        cleanup_status = "succeeded"
        try:
            _remove_tree(_staging_directory(user_id, staging_id))
        except OSError:
            cleanup_status = "failed"
            current_app.logger.warning(
                "Backup restore staging cleanup failed for audit run %s",
                audit_run.id,
            )
        if audit_run.metadata_json is not None:
            audit_run.metadata_json = {
                **audit_run.metadata_json,
                "cleanup_status": cleanup_status,
            }
            db.session.add(audit_run)
            db.session.commit()

        return {
            **result_summary,
            "committed": True,
            "rollback": False,
            "audit_run_id": audit_run.id,
            "cleanup_status": cleanup_status,
            "account": account_result,
            "files": file_result,
        }

    @staticmethod
    def file_plan_sha256(plan: dict[str, Any]) -> str:
        return canonical_sha256(
            {
                key: plan.get(key)
                for key in (
                    "total",
                    "valid",
                    "invalid",
                    "inserts",
                    "updates",
                    "skips",
                    "conflicts",
                    "unsupported",
                    "bytes",
                    "operations",
                )
            }
        )

    def cleanup_staging(self, *, user_id: int, staging_id: str) -> None:
        _remove_tree(_staging_directory(user_id, staging_id))

    def _inspection(self, *, staging_id: str, user_id: int) -> BackupInspection:
        archive_path = _staging_directory(user_id, staging_id) / "backup.zip"
        if not archive_path.is_file():
            raise BackupError("Backup staging reference is missing or expired")
        return self.reader.inspect(archive_path)

    def _file_plan(
        self,
        inspection: BackupInspection,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        operations: list[dict[str, Any]] = []
        warnings: list[str] = []
        for entry in inspection.manifest["entries"]:
            if entry["kind"] == "account_export":
                continue
            if entry["kind"] == "raw_upload":
                existing = db.session.execute(
                    db.select(UploadedFile).where(
                        UploadedFile.user_id == user_id,
                        UploadedFile.sha256 == entry["sha256"],
                    )
                ).scalar_one_or_none()
            else:
                format_name = entry["metadata"].get("format", "bin")
                existing = db.session.execute(
                    db.select(ExportRecord).where(
                        ExportRecord.user_id == user_id,
                        ExportRecord.sha256 == entry["sha256"],
                        ExportRecord.format == format_name,
                        ExportRecord.status == "ready",
                    )
                ).scalar_one_or_none()
                if (
                    existing is None
                    and entry.get("source_record_type")
                    and entry.get("source_record_id")
                ):
                    warnings.append(
                        f"Generated file {entry['logical_id']} will be restored without an unsafe source link if remapping is unavailable."
                    )
            operations.append(
                {
                    "operation": "skip" if existing else "insert",
                    "kind": entry["kind"],
                    "logical_id": entry["logical_id"],
                    "sha256": entry["sha256"],
                    "size_bytes": entry["size_bytes"],
                    "existing_id": existing.id if existing else None,
                }
            )
        return _file_summary(operations, warnings=warnings)

    def _build_token(
        self,
        *,
        user_id: int,
        staging_id: str,
        inspection: BackupInspection,
        account_plan_sha256: str,
        file_plan: dict[str, Any],
    ) -> str:
        return _serializer().dumps(
            {
                "version": BACKUP_TOKEN_VERSION,
                "mode": "full_backup_restore",
                "user_id": user_id,
                "staging_id": staging_id,
                "backup_sha256": inspection.backup_sha256,
                "manifest_sha256": inspection.manifest_sha256,
                "account_plan_sha256": account_plan_sha256,
                "file_plan_sha256": self.file_plan_sha256(file_plan),
            },
            salt=BACKUP_TOKEN_SALT,
        )

    def _verify_token(
        self,
        token: str,
        *,
        user_id: int,
        staging_id: str,
        inspection: BackupInspection,
        account_plan_sha256: str,
        file_plan: dict[str, Any],
        max_age: int = BACKUP_TOKEN_MAX_AGE_SECONDS,
    ) -> None:
        try:
            data = _serializer().loads(token, salt=BACKUP_TOKEN_SALT, max_age=max_age)
        except SignatureExpired as error:
            raise BackupTokenError("Backup confirmation token expired") from error
        except BadSignature as error:
            raise BackupTokenError("Backup confirmation token is invalid") from error
        expected = {
            "version": BACKUP_TOKEN_VERSION,
            "mode": "full_backup_restore",
            "user_id": user_id,
            "staging_id": staging_id,
            "backup_sha256": inspection.backup_sha256,
            "manifest_sha256": inspection.manifest_sha256,
            "account_plan_sha256": account_plan_sha256,
            "file_plan_sha256": self.file_plan_sha256(file_plan),
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise BackupTokenError(
                "Backup or restore plan changed; preview and confirm again"
            )

    def _restore_files(
        self,
        inspection: BackupInspection,
        *,
        file_plan: dict[str, Any],
        account_result: dict[str, Any],
        user_id: int,
        staging_id: str,
        moved_paths: list[Path],
        temporary_paths: list[Path],
    ) -> dict[str, Any]:
        operation_by_id = {
            operation["logical_id"]: operation
            for operation in file_plan["operations"]
        }
        destination_ids = _destination_id_map(account_result)
        result_operations: list[dict[str, Any]] = []
        extraction_root = _staging_directory(user_id, staging_id) / "extracted"
        extraction_root.mkdir(parents=True, exist_ok=True)
        restored_raw_ids: dict[int, int] = {}

        for entry in inspection.manifest["entries"]:
            if entry["kind"] == "account_export":
                continue
            planned = operation_by_id[entry["logical_id"]]
            if planned["operation"] == "skip":
                source_upload_id = entry.get("source_record_id")
                if (
                    entry["kind"] == "raw_upload"
                    and isinstance(source_upload_id, int)
                    and isinstance(planned.get("existing_id"), int)
                ):
                    restored_raw_ids[source_upload_id] = planned["existing_id"]
                result_operations.append(planned)
                continue
            extracted = extraction_root / f"{entry['logical_id']}.bin"
            self.reader.extract_verified_entry(inspection, entry, extracted)
            temporary_paths.append(extracted)

            if entry["kind"] == "raw_upload":
                record, final = self._restore_raw_record(
                    entry,
                    extracted=extracted,
                    user_id=user_id,
                )
            else:
                record, final = self._restore_generated_record(
                    entry,
                    extracted=extracted,
                    user_id=user_id,
                    destination_ids=destination_ids,
                )
            db.session.flush()
            source_upload_id = entry.get("source_record_id")
            if entry["kind"] == "raw_upload" and isinstance(source_upload_id, int):
                restored_raw_ids[source_upload_id] = record.id
            if extracted.exists():
                final.parent.mkdir(parents=True, exist_ok=True)
                if final.exists():
                    digest, size = _sha256_path(final)
                    if digest != entry["sha256"] or size != entry["size_bytes"]:
                        raise BackupError("Restore destination collision failed integrity check")
                    extracted.unlink(missing_ok=True)
                else:
                    os.replace(extracted, final)
                    moved_paths.append(final)
            result_operations.append(
                {**planned, "existing_id": record.id}
            )
        self._link_restored_source_files(
            inspection.account_payload,
            account_result=account_result,
            restored_raw_ids=restored_raw_ids,
            user_id=user_id,
        )
        return _file_summary(result_operations, warnings=file_plan["warnings"])

    @staticmethod
    def _link_restored_source_files(
        account_payload: dict[str, Any],
        *,
        account_result: dict[str, Any],
        restored_raw_ids: dict[int, int],
        user_id: int,
    ) -> None:
        operations = {
            (item.get("section"), item.get("index")): item
            for item in account_result.get("operations", [])
        }
        data = account_payload.get("data") or {}
        for section, model in (("activities", Activity), ("routes", Route)):
            for index, document in enumerate(data.get(section) or []):
                source_file_id = document.get("source_file_id")
                destination_file_id = restored_raw_ids.get(source_file_id)
                operation = operations.get((section, index), {})
                destination_record_id = operation.get("existing_id")
                if not destination_file_id or not destination_record_id:
                    continue
                record = db.session.get(model, destination_record_id)
                if record is None or record.user_id != user_id:
                    raise BackupError("Restored source file link is not owned by destination user")
                record.source_file_id = destination_file_id
                db.session.add(record)

    @staticmethod
    def _restore_raw_record(
        entry: dict[str, Any],
        *,
        extracted: Path,
        user_id: int,
    ) -> tuple[UploadedFile, Path]:
        final = (
            Path(current_app.config["UPLOAD_ROOT"])
            / f"user_{user_id}"
            / entry["sha256"]
        )
        metadata = entry.get("metadata") or {}
        source_type = metadata.get("source_type")
        if source_type not in _UPLOAD_SOURCE_TYPES:
            source_type = "uploaded"
        import_status = metadata.get("import_status")
        if import_status not in _UPLOAD_STATUSES:
            import_status = "pending"
        detected_type = _safe_token_value(
            metadata.get("detected_type"),
            32,
            "unknown",
        )
        record = UploadedFile(
            user_id=user_id,
            original_filename=_safe_original_filename(entry.get("original_filename")),
            stored_filename=entry["sha256"],
            storage_path=_relative_to_data(final),
            source_type=source_type,
            detected_type=detected_type,
            import_status=import_status,
            error_message=None,
            sha256=entry["sha256"],
            size_bytes=entry["size_bytes"],
            mime_type=_safe_media_type(entry.get("media_type")),
        )
        db.session.add(record)
        return record, final

    @staticmethod
    def _restore_generated_record(
        entry: dict[str, Any],
        *,
        extracted: Path,
        user_id: int,
        destination_ids: dict[tuple[str, int], int],
    ) -> tuple[ExportRecord, Path]:
        metadata = entry.get("metadata") or {}
        format_name = _safe_token_value(metadata.get("format"), 32, "bin")
        suffix = Path(_safe_original_filename(entry.get("original_filename"))).suffix
        suffix = suffix if len(suffix) <= 16 else ""
        final = (
            Path(current_app.config["GENERATED_UPLOAD_ROOT"])
            / "restored"
            / f"user_{user_id}"
            / f"{uuid.uuid4().hex}{suffix}"
        )
        source_type = _safe_token_value(
            entry.get("source_record_type"),
            64,
            None,
        )
        source_old_id = entry.get("source_record_id")
        source_id = (
            destination_ids.get((source_type, source_old_id))
            if source_type and isinstance(source_old_id, int)
            else None
        )
        record = ExportRecord(
            user_id=user_id,
            domain=_safe_token_value(metadata.get("domain"), 64, "restored_export"),
            source_type=_safe_token_value(metadata.get("source_type"), 64, "restored"),
            source_id=source_id,
            format=format_name,
            exporter_version=_safe_token_value(
                metadata.get("exporter_version"), 20, "unknown"
            ),
            filename=_safe_original_filename(entry.get("original_filename")),
            relative_path=_relative_to_data(final),
            media_type=_safe_media_type(entry.get("media_type")) or "application/octet-stream",
            size_bytes=entry["size_bytes"],
            sha256=entry["sha256"],
            status="ready",
            warnings_json=(
                ["Restored from full backup without source object link."]
                if source_old_id and source_id is None
                else ["Restored from full backup."]
            ),
        )
        db.session.add(record)
        return record, final


def _safe_token_value(value: Any, maximum: int, fallback: str | None) -> str | None:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or not _SAFE_TOKEN.fullmatch(normalized):
        return fallback
    return normalized


def _safe_media_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255 or any(
        character in normalized for character in "\r\n\x00"
    ):
        return None
    return normalized


def _file_summary(
    operations: list[dict[str, Any]],
    *,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "total": len(operations),
        "valid": sum(item["operation"] in {"insert", "update", "skip"} for item in operations),
        "invalid": sum(item["operation"] == "invalid" for item in operations),
        "inserts": sum(item["operation"] == "insert" for item in operations),
        "updates": sum(item["operation"] == "update" for item in operations),
        "skips": sum(item["operation"] == "skip" for item in operations),
        "conflicts": sum(item["operation"] == "conflict" for item in operations),
        "unsupported": sum(item["operation"] == "unsupported" for item in operations),
        "bytes": sum(item.get("size_bytes", 0) for item in operations),
        "operations": operations,
        "warnings": warnings,
        "errors": [
            error
            for item in operations
            for error in item.get("errors", [])
        ],
    }


def _combined_summary(*plans: dict[str, Any]) -> dict[str, Any]:
    operations = [
        operation
        for plan in plans
        for operation in plan.get("operations", [])
    ]
    return {
        "total": sum(int(plan.get("total") or 0) for plan in plans),
        "valid": sum(int(plan.get("valid") or 0) for plan in plans),
        "invalid": sum(int(plan.get("invalid") or 0) for plan in plans),
        "inserts": sum(int(plan.get("inserts") or 0) for plan in plans),
        "updates": sum(int(plan.get("updates") or 0) for plan in plans),
        "skips": sum(int(plan.get("skips") or 0) for plan in plans),
        "conflicts": sum(int(plan.get("conflicts") or 0) for plan in plans),
        "unsupported": sum(int(plan.get("unsupported") or 0) for plan in plans),
        "operations": operations,
        "errors": [error for plan in plans for error in plan.get("errors", [])],
    }


def _destination_id_map(
    account_result: dict[str, Any],
) -> dict[tuple[str, int], int]:
    section_to_domain = {
        "food_products": "food_product",
        "recipes": "recipe",
        "weigh_ins": "weigh_in",
        "daily_energy": "daily_energy",
        "daily_nutrition": "daily_nutrition",
        "medical_lab_reports": "medical_lab",
        "training_plans": "training_plan",
        "training_sessions": "training_session",
        "activities": "activity",
        "routes": "route",
    }
    result: dict[tuple[str, int], int] = {}
    for operation in account_result.get("operations", []):
        source_id = operation.get("source_id")
        destination_id = operation.get("existing_id")
        domain = section_to_domain.get(operation.get("section"))
        if domain and isinstance(source_id, int) and isinstance(destination_id, int):
            result[(domain, source_id)] = destination_id
    return result


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    root = _staging_root().resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise BackupError("Refusing to remove a path outside backup staging") from error
    for child in sorted(resolved.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_symlink():
            child.unlink(missing_ok=True)
        elif child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    resolved.rmdir()
