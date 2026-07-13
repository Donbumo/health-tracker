import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import ExportRecord
from app.services.exporters.base import ExportError, ExportPreview, ExportSpec


MAX_EXPORT_BYTES = 25 * 1024 * 1024
MAX_WARNING_LENGTH = 500
MAX_WARNINGS = 50


class ExportStorageError(ExportError):
    pass


class ExportArtifactService:
    def preview(
        self,
        spec: ExportSpec,
        resource: Any,
        *,
        user_id: int,
        context: dict[str, Any] | None = None,
    ) -> ExportPreview:
        safe_context = dict(context or {})
        capability = spec.capability(resource, user_id, safe_context)
        filename = _download_filename(spec.filename(resource, safe_context), spec.extension)
        return ExportPreview(
            domain=spec.domain,
            format_name=spec.format_name,
            extension=spec.extension,
            media_type=spec.media_type,
            filename=filename,
            capability=capability,
        )

    def generate(
        self,
        spec: ExportSpec,
        resource: Any,
        *,
        user_id: int,
        source_type: str,
        source_id: int | None,
        context: dict[str, Any] | None = None,
    ) -> ExportRecord:
        safe_context = dict(context or {})
        preview = self.preview(spec, resource, user_id=user_id, context=safe_context)
        if not preview.capability.supported:
            raise ExportError(preview.capability.reason or "This format is not supported")

        artifact = spec.render(resource, user_id, safe_context)
        if artifact.extension != spec.extension or artifact.mimetype != spec.media_type:
            raise ExportError("Exporter returned an unexpected format")
        if len(artifact.content) > MAX_EXPORT_BYTES:
            raise ExportError("Generated export exceeds the allowed size")

        warnings = list(preview.capability.warnings)
        if artifact.warning:
            warnings.append(artifact.warning)
        warnings = _safe_warnings(warnings)

        root = Path(current_app.config["GENERATED_UPLOAD_ROOT"])
        user_directory = root / "exports" / f"user_{user_id}"
        user_directory.mkdir(parents=True, exist_ok=True)
        internal_name = f"{uuid.uuid4().hex}.{spec.extension}"
        final_path = user_directory / internal_name
        temporary_path = user_directory / f".{uuid.uuid4().hex}.generating"
        digest = hashlib.sha256(artifact.content).hexdigest()

        try:
            with temporary_path.open("xb") as stream:
                stream.write(artifact.content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, final_path)

            relative_path = (
                Path("uploads")
                / "generated"
                / "exports"
                / f"user_{user_id}"
                / internal_name
            ).as_posix()
            record = ExportRecord(
                user_id=user_id,
                domain=spec.domain,
                source_type=source_type[:64],
                source_id=source_id,
                format=spec.format_name,
                exporter_version=spec.exporter_version,
                filename=preview.filename,
                relative_path=relative_path,
                media_type=spec.media_type,
                size_bytes=len(artifact.content),
                sha256=digest,
                status="ready",
                warnings_json=warnings or None,
            )
            db.session.add(record)
            db.session.commit()
            return record
        except Exception:
            db.session.rollback()
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

    def resolve_download(self, record: ExportRecord, *, user_id: int) -> Path:
        if record.user_id != user_id:
            raise ExportStorageError("Export does not belong to this user")
        if record.status != "ready":
            raise ExportStorageError("Export is not available")
        if record.expires_at is not None:
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                record.status = "expired"
                db.session.commit()
                raise ExportStorageError("Export has expired")

        root = Path(current_app.config["GENERATED_UPLOAD_ROOT"]).resolve()
        data_root = Path(current_app.config["DATA_ROOT"])
        candidate = data_root / record.relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise ExportStorageError("Export file is missing") from error
        if not resolved.is_relative_to(root) or candidate.is_symlink() or resolved.is_symlink():
            raise ExportStorageError("Export path is not safe")
        if not resolved.is_file():
            raise ExportStorageError("Export file is missing")
        content = resolved.read_bytes()
        if len(content) != record.size_bytes:
            raise ExportStorageError("Export file size does not match its record")
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise ExportStorageError("Export file checksum does not match its record")
        return resolved

    def delete(self, record: ExportRecord, *, user_id: int) -> None:
        if record.user_id != user_id:
            raise ExportStorageError("Export does not belong to this user")
        if record.status == "deleted":
            return
        try:
            path = self.resolve_download(record, user_id=user_id)
        except ExportStorageError as error:
            if str(error) not in {"Export file is missing", "Export is not available"}:
                raise
        else:
            path.unlink(missing_ok=True)
        record.status = "deleted"
        db.session.commit()


def _download_filename(value: str, extension: str) -> str:
    cleaned = secure_filename(value)[:220]
    if not cleaned:
        cleaned = "health_tracker_export"
    suffix = f".{extension}"
    if not cleaned.casefold().endswith(suffix.casefold()):
        cleaned += suffix
    return cleaned[:255]


def _safe_warnings(values: list[str]) -> list[str]:
    return [str(value).strip()[:MAX_WARNING_LENGTH] for value in values[:MAX_WARNINGS] if str(value).strip()]
