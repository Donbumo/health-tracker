from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
from pathlib import Path, PurePath
import re
import uuid

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import MedicalDocument, MedicalStudy, UploadedFile
from app.services.medical_records import _audit, owned_document, owned_study
from app.services.mobile_sync import MobileSyncError


ALLOWED_MIME_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "application/json": {".json"},
    "text/csv": {".csv"},
}


def sanitized_filename(value: str | None) -> str:
    name = PurePath(str(value or "").replace("\\", "/")).name
    name = "".join(character for character in name if character.isprintable() and character not in {'"', "'", ";"})
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        raise MobileSyncError("invalid_filename", "El nombre del documento no es válido.")
    return name[:255]


def _detected_mime(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        if b"/Encrypt" in content:
            raise MobileSyncError("encrypted_document", "No se aceptan PDF cifrados que no puedan inspeccionarse.", 415)
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise MobileSyncError("unsupported_document", "El tipo real del documento no está permitido.", 415) from error
    stripped = text.lstrip()
    if stripped.startswith(("<", "<!DOCTYPE", "<?xml")):
        raise MobileSyncError("active_content_rejected", "No se acepta contenido HTML, SVG o XML activo.", 415)
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (json.JSONDecodeError, ValueError) as error:
            raise MobileSyncError("invalid_json", "El documento JSON no es válido.", 415) from error
        if not isinstance(parsed, dict) or parsed.get("format") != "health-tracker-medical-lab-v1":
            raise MobileSyncError("invalid_json", "El JSON médico no usa el formato interno permitido.", 415)
        return "application/json"
    try:
        reader = csv.reader(StringIO(text, newline=""), strict=True)
        header = next(reader)
    except (csv.Error, StopIteration) as error:
        raise MobileSyncError("unsupported_document", "El tipo real del documento no está permitido.", 415) from error
    if "format" not in header or "study_date" not in header or "display_name" not in header:
        raise MobileSyncError("invalid_csv", "El CSV médico no usa la plantilla versionada.", 415)
    return "text/csv"


def inspect_upload(storage: FileStorage) -> tuple[bytes, str, str, str]:
    if storage is None or not storage.filename:
        raise MobileSyncError("file_required", "Selecciona un documento.")
    filename = sanitized_filename(storage.filename)
    maximum = int(current_app.config["MEDICAL_DOCUMENT_MAX_BYTES"])
    content = storage.stream.read(maximum + 1)
    if not content:
        raise MobileSyncError("empty_document", "El documento está vacío.")
    if len(content) > maximum:
        raise MobileSyncError("document_too_large", "El documento supera el límite permitido.", 413)
    mime = _detected_mime(content)
    extension = Path(filename).suffix.casefold()
    if extension not in ALLOWED_MIME_EXTENSIONS[mime]:
        raise MobileSyncError("mime_mismatch", "La extensión no coincide con el contenido del documento.", 415)
    supplied = (storage.mimetype or "").split(";", 1)[0].strip().casefold()
    if supplied and supplied not in {mime, "application/octet-stream", "image/jpg" if mime == "image/jpeg" else mime}:
        raise MobileSyncError("mime_mismatch", "El MIME declarado no coincide con el contenido del documento.", 415)
    return content, filename, mime, hashlib.sha256(content).hexdigest()


def _user_storage_bytes(user_id: int) -> int:
    return int(db.session.execute(
        db.select(db.func.coalesce(db.func.sum(UploadedFile.size_bytes), 0)).where(
            UploadedFile.user_id == user_id,
            UploadedFile.source_type == "medical_document",
        )
    ).scalar_one())


def store_document(
    study: MedicalStudy,
    *,
    content: bytes,
    filename: str,
    mime_type: str,
    sha256: str,
    document_type="original",
    source="mobile",
) -> tuple[MedicalDocument, bool]:
    if document_type not in {"original", "supporting", "medical_json", "controlled_csv"}:
        raise MobileSyncError("invalid_document_type", "document_type no está soportado.")
    duplicate = db.session.execute(db.select(MedicalDocument).where(
        MedicalDocument.user_id == study.user_id,
        MedicalDocument.study_id == study.id,
        MedicalDocument.sha256 == sha256,
    )).scalar_one_or_none()
    if duplicate is not None:
        return duplicate, True
    existing_upload = db.session.execute(db.select(UploadedFile).where(
        UploadedFile.user_id == study.user_id,
        UploadedFile.sha256 == sha256,
    )).scalar_one_or_none()
    if existing_upload is None:
        if _user_storage_bytes(study.user_id) + len(content) > int(current_app.config["MEDICAL_DOCUMENT_USER_MAX_BYTES"]):
            raise MobileSyncError("medical_storage_limit", "Los documentos médicos superan el límite de la cuenta.", 413)
        root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
        directory = root / f"user_{study.user_id}" / "medical"
        directory.mkdir(parents=True, exist_ok=True)
        stored_name = uuid.uuid4().hex
        final = directory / stored_name
        temporary = directory / f".{stored_name}.uploading"
        try:
            with temporary.open("xb") as destination:
                destination.write(content)
            temporary.replace(final)
        finally:
            temporary.unlink(missing_ok=True)
        data_root = Path(current_app.config["DATA_ROOT"]).resolve()
        try:
            relative = final.resolve().relative_to(data_root).as_posix()
        except ValueError as error:
            final.unlink(missing_ok=True)
            raise MobileSyncError("storage_invalid", "El storage configurado no es seguro.", 500) from error
        existing_upload = UploadedFile(
            user_id=study.user_id,
            original_filename=filename,
            stored_filename=stored_name,
            storage_path=relative,
            source_type="medical_document",
            detected_type="medical_document",
            import_status="imported",
            sha256=sha256,
            size_bytes=len(content),
            mime_type=mime_type,
        )
        db.session.add(existing_upload)
        db.session.flush()
    row = MedicalDocument(
        user_id=study.user_id,
        study_id=study.id,
        uploaded_file_id=existing_upload.id,
        document_type=document_type,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=sha256,
        availability="available",
        source=source,
    )
    db.session.add(row)
    study.revision += 1
    _audit(study.user_id, study.public_id, "document_added", entity_type="document",
           entity_public_id=row.public_id, counts={"document_count": len(study.documents) + 1, "revision": study.revision})
    db.session.flush()
    return row, False


def resolve_download(document: MedicalDocument, user_id: int) -> Path:
    if document.user_id != user_id or document.study.user_id != user_id:
        raise MobileSyncError("not_found", "Documento no encontrado.", 404)
    upload = document.uploaded_file
    if upload is None or upload.user_id != user_id or document.availability != "available":
        raise MobileSyncError("document_unavailable", "El documento original no está disponible.", 410)
    root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    data_root = Path(current_app.config["DATA_ROOT"]).resolve()
    path = (data_root / upload.storage_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise MobileSyncError("document_unavailable", "El documento original no está disponible.", 410) from error
    if path.is_symlink() or not path.is_file() or path.stat().st_size != document.size_bytes:
        raise MobileSyncError("document_unavailable", "El documento original no está disponible.", 410)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != document.sha256:
        raise MobileSyncError("document_integrity_failed", "La integridad del documento no coincide.", 409)
    return path


def delete_document(user_id: int, public_id: str, payload: dict) -> tuple[dict, Path | None]:
    if set(payload) != {"base_revision", "confirmed"} or payload.get("confirmed") is not True:
        raise MobileSyncError("confirmation_required", "La eliminación del documento requiere confirmación explícita.")
    row = owned_document(user_id, public_id)
    if payload.get("base_revision") != row.revision:
        raise MobileSyncError("revision_conflict", "El documento cambió en el servidor.", 409,
                              {"server_revision": row.revision, "conflict_code": "stale_revision"})
    study = row.study
    upload = row.uploaded_file
    result = {"public_id": row.public_id, "deleted": True, "study_public_id": study.public_id}
    _audit(user_id, study.public_id, "document_removed", entity_type="document", entity_public_id=row.public_id,
           counts={"document_count": max(0, len(study.documents) - 1), "revision": study.revision + 1})
    db.session.delete(row)
    db.session.flush()
    cleanup = None
    if upload is not None and upload.source_type == "medical_document":
        references = db.session.execute(db.select(db.func.count(MedicalDocument.id)).where(
            MedicalDocument.uploaded_file_id == upload.id
        )).scalar_one()
        if references == 0:
            data_root = Path(current_app.config["DATA_ROOT"]).resolve()
            candidate = (data_root / upload.storage_path).resolve()
            root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                candidate = None
            if candidate is not None and not candidate.is_symlink():
                cleanup = candidate
            db.session.delete(upload)
    study.revision += 1
    db.session.flush()
    return result, cleanup


def permanent_delete_study(user_id: int, public_id: str, payload: dict) -> tuple[dict, list[Path]]:
    expected = {"base_revision", "confirmed", "impact_acknowledged"}
    if set(payload) != expected or payload.get("confirmed") is not True or payload.get("impact_acknowledged") is not True:
        raise MobileSyncError("confirmation_required", "La eliminación definitiva requiere confirmación e impacto aceptado.")
    study = owned_study(user_id, public_id, lock=True)
    if payload.get("base_revision") != study.revision:
        raise MobileSyncError("revision_conflict", "El estudio cambió en el servidor.", 409,
                              {"server_revision": study.revision, "conflict_code": "stale_revision"})
    cleanup: list[Path] = []
    uploads = {document.uploaded_file_id: document.uploaded_file for document in study.documents if document.uploaded_file_id}
    _audit(user_id, study.public_id, "permanently_deleted", counts={
        "panel_count": len(study.panels),
        "result_count": sum(len(panel.results) for panel in study.panels),
        "document_count": len(study.documents),
        "revision": study.revision,
    })
    db.session.delete(study)
    db.session.flush()
    data_root = Path(current_app.config["DATA_ROOT"]).resolve()
    root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    for upload_id, upload in uploads.items():
        if upload is None or upload.source_type != "medical_document":
            continue
        references = db.session.execute(db.select(db.func.count(MedicalDocument.id)).where(
            MedicalDocument.uploaded_file_id == upload_id
        )).scalar_one()
        if references:
            continue
        candidate = (data_root / upload.storage_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            candidate = None
        if candidate is not None and not candidate.is_symlink():
            cleanup.append(candidate)
        db.session.delete(upload)
    return {"public_id": public_id, "deleted": True}, cleanup
