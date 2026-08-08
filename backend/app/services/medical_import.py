from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import uuid

from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import LabPanel, LabResult, MedicalDocument, MedicalStudy
from app.services.medical_documents import sanitized_filename
from app.services.medical_records import (
    MEDICAL_WARNING,
    _audit,
    create_study,
    owned_study,
    serialize_study,
)
from app.services.mobile_sync import MobileSyncError
from app.services.validation import JsonSchemaValidationError, validate_json_document


FORMAT = "health-tracker-medical-lab-v1"
CSV_HEADERS = (
    "format", "schema_version", "study_public_id", "study_type", "title",
    "laboratory_name", "professional_name", "study_date", "issued_date",
    "timezone", "study_notes", "state", "panel_public_id", "panel_name",
    "panel_order", "result_public_id", "display_name", "canonical_key",
    "value_type", "original_value", "numeric_value", "comparator",
    "original_unit", "reference_lower", "reference_upper", "reference_text",
    "source_status", "method", "specimen", "result_notes", "result_order",
)


def _json_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["API_TOKEN_SIGNING_KEY"],
        salt="health-tracker-medical-import-preview-v1",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def _load_text(storage: FileStorage) -> tuple[str, str]:
    if storage is None or not storage.filename:
        raise MobileSyncError("file_required", "Selecciona un JSON o CSV médico.")
    filename = sanitized_filename(storage.filename)
    maximum = min(int(current_app.config["MEDICAL_DOCUMENT_MAX_BYTES"]), 8 * 1024 * 1024)
    content = storage.stream.read(maximum + 1)
    if not content:
        raise MobileSyncError("empty_document", "El archivo está vacío.")
    if len(content) > maximum:
        raise MobileSyncError("document_too_large", "El archivo supera el límite permitido.", 413)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise MobileSyncError("invalid_encoding", "El archivo debe usar UTF-8.") from error
    extension = Path(filename).suffix.casefold()
    if extension not in {".json", ".csv"}:
        raise MobileSyncError("unsupported_document", "Solo se admite JSON o CSV médico controlado.", 415)
    return text, extension[1:]


def _strict_json(text: str) -> dict:
    try:
        value = json.loads(text, parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (json.JSONDecodeError, ValueError) as error:
        raise MobileSyncError("invalid_json", "El JSON médico no es válido.") from error
    if not isinstance(value, dict):
        raise MobileSyncError("invalid_json", "El JSON médico debe ser un objeto.")
    return value


def _formula_cell(value: str, field: str, value_type: str) -> bool:
    stripped = value.lstrip()
    if not stripped:
        return False
    if stripped[0] in {"=", "+", "@"}:
        return True
    if stripped[0] == "-":
        if field in {"numeric_value", "reference_lower", "reference_upper"}:
            return False
        if field == "original_value" and value_type == "numeric":
            try:
                float(stripped)
                return False
            except ValueError:
                pass
        return True
    return False


def _csv_document(text: str) -> tuple[dict | None, list[dict]]:
    errors: list[dict] = []
    try:
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != CSV_HEADERS:
            unknown = sorted(set(reader.fieldnames or ()) - set(CSV_HEADERS))
            missing = sorted(set(CSV_HEADERS) - set(reader.fieldnames or ()))
            detail = []
            if unknown:
                detail.append("columnas desconocidas: " + ", ".join(unknown))
            if missing:
                detail.append("columnas faltantes: " + ", ".join(missing))
            return None, [{"row": 1, "code": "invalid_headers", "message": "; ".join(detail) or "orden de encabezados inválido"}]
        rows = []
        maximum_rows = int(current_app.config["MEDICAL_CSV_MAX_ROWS"])
        maximum_cell = int(current_app.config["MEDICAL_CSV_MAX_CELL_BYTES"])
        for number, row in enumerate(reader, start=2):
            if len(rows) >= maximum_rows:
                errors.append({"row": number, "code": "too_many_rows", "message": "El CSV supera el máximo de filas."})
                break
            row_error = False
            for field, value in row.items():
                value = value or ""
                if len(value.encode("utf-8")) > maximum_cell:
                    errors.append({"row": number, "field": field, "code": "cell_too_large", "message": "La celda supera el límite."})
                    row_error = True
                if _formula_cell(value, field, row.get("value_type", "")):
                    errors.append({"row": number, "field": field, "code": "formula_rejected", "message": "La celda parece una fórmula y fue rechazada."})
                    row_error = True
            if row.get("format") != FORMAT or row.get("schema_version") != "1.0":
                errors.append({"row": number, "code": "unsupported_format", "message": "La fila no declara el formato v1."})
                row_error = True
            if not row_error:
                rows.append(row)
    except csv.Error as error:
        return None, [{"row": 0, "code": "invalid_csv", "message": str(error)[:200]}]
    if errors or not rows:
        if not rows and not errors:
            errors.append({"row": 2, "code": "empty_csv", "message": "El CSV no contiene resultados."})
        return None, errors
    identity = tuple(rows[0].get(field, "") for field in (
        "study_public_id", "study_type", "title", "laboratory_name",
        "professional_name", "study_date", "issued_date", "timezone", "study_notes", "state",
    ))
    for number, row in enumerate(rows[1:], start=3):
        if tuple(row.get(field, "") for field in (
            "study_public_id", "study_type", "title", "laboratory_name",
            "professional_name", "study_date", "issued_date", "timezone", "study_notes", "state",
        )) != identity:
            errors.append({"row": number, "code": "multiple_studies", "message": "Todas las filas deben pertenecer al mismo estudio."})
    if errors:
        return None, errors
    first = rows[0]
    study_public_id = first["study_public_id"] or str(uuid.uuid4())
    panels: dict[str, dict] = {}
    for row in rows:
        panel_key = row["panel_public_id"] or row["panel_name"].strip().casefold()
        panel = panels.setdefault(panel_key, {
            "public_id": row["panel_public_id"] or str(uuid.uuid4()),
            "name": row["panel_name"],
            "display_order": int(row["panel_order"] or len(panels)),
            "source": "csv_import",
            "revision": 1,
            "results": [],
        })
        panel["results"].append({
            "public_id": row["result_public_id"] or str(uuid.uuid4()),
            "display_name": row["display_name"],
            "canonical_key": row["canonical_key"] or None,
            "value_type": row["value_type"],
            "original_value": row["original_value"],
            "numeric_value": row["numeric_value"] or None,
            "comparator": row["comparator"] or "none",
            "original_unit": row["original_unit"] or None,
            "reference_lower": row["reference_lower"] or None,
            "reference_upper": row["reference_upper"] or None,
            "reference_text": row["reference_text"] or None,
            "source_status": row["source_status"] or "not_provided",
            "method": row["method"] or None,
            "specimen": row["specimen"] or None,
            "notes": row["result_notes"] or None,
            "display_order": int(row["result_order"] or len(panel["results"])),
            "source": "csv_import",
            "revision": 1,
        })
    document = {
        "format": FORMAT,
        "schema_version": "1.0",
        "study": {
            "public_id": study_public_id,
            "study_type": first["study_type"],
            "title": first["title"],
            "laboratory_name": first["laboratory_name"] or None,
            "professional_name": first["professional_name"] or None,
            "study_date": first["study_date"],
            "issued_date": first["issued_date"] or None,
            "timezone": first["timezone"] or None,
            "notes": first["study_notes"] or None,
            "state": first["state"] or "complete",
            "source": "csv_import",
            "revision": 1,
        },
        "panels": sorted(panels.values(), key=lambda item: item["display_order"]),
        "attachments": [],
    }
    return document, []


def _fingerprint(document: dict) -> str | None:
    study = document["study"]
    if study["study_type"] != "laboratory" or not document["panels"]:
        return None
    panel_hashes = []
    for panel in sorted(document["panels"], key=lambda item: item["display_order"]):
        data = [{
            "name": result["display_name"].casefold(),
            "key": result.get("canonical_key"),
            "type": result["value_type"],
            "value": result["original_value"],
            "unit": result.get("original_unit"),
            "lower": result.get("reference_lower"),
            "upper": result.get("reference_upper"),
            "text": result.get("reference_text"),
            "method": result.get("method"),
        } for result in sorted(panel["results"], key=lambda item: (item["display_order"], item["public_id"]))]
        panel_hashes.append(_json_hash(data))
    return _json_hash({
        "date": study["study_date"],
        "laboratory": (study.get("laboratory_name") or "").strip().casefold(),
        "panels": panel_hashes,
    })


def _classification(user_id: int, document: dict) -> tuple[str, MedicalStudy | None]:
    study = document["study"]
    fingerprint = _fingerprint(document)
    if fingerprint:
        exact = db.session.execute(db.select(MedicalStudy).where(
            MedicalStudy.user_id == user_id,
            MedicalStudy.structured_fingerprint == fingerprint,
        ).limit(1)).scalar_one_or_none()
        if exact:
            return "exact_structured_duplicate", exact
    same_lab = db.session.execute(db.select(MedicalStudy).where(
        MedicalStudy.user_id == user_id,
        MedicalStudy.study_date == study["study_date"],
        MedicalStudy.laboratory_name == study.get("laboratory_name"),
    ).limit(1)).scalar_one_or_none()
    if same_lab:
        return "probable_duplicate", same_lab
    same_date = db.session.execute(db.select(MedicalStudy).where(
        MedicalStudy.user_id == user_id,
        MedicalStudy.study_date == study["study_date"],
    ).limit(1)).scalar_one_or_none()
    if same_date:
        return "possible_duplicate", same_date
    return "distinct", None


def preview_import(user_id: int, storage: FileStorage) -> dict:
    text, source_format = _load_text(storage)
    errors = []
    if source_format == "json":
        try:
            document = _strict_json(text)
        except MobileSyncError as error:
            document = None
            errors.append({"row": 0, "code": error.code, "message": str(error)})
    else:
        document, errors = _csv_document(text)
    if document is not None:
        try:
            validate_json_document(document, "medical_study")
        except JsonSchemaValidationError as error:
            errors.extend({"row": 0, "code": "schema_error", "message": item} for item in error.errors[:100])
    valid = document is not None and not errors
    classification, existing = _classification(user_id, document) if valid else ("distinct", None)
    warnings = []
    if classification in {"probable_duplicate", "possible_duplicate"}:
        warnings.append("Se encontró un posible duplicado; se conservará hasta que el usuario decida.")
    token = _serializer().dumps({"user": user_id, "hash": _json_hash(document), "format": source_format}) if valid else None
    preview = {
        "schema_version": "1.0",
        "format": FORMAT,
        "valid": valid,
        "read_only": True,
        "source_format": source_format,
        "row_count": sum(len(panel["results"]) for panel in document["panels"]) if valid else 0,
        "new_count": 0 if classification == "exact_structured_duplicate" else (1 if valid else 0),
        "duplicate_count": 1 if classification != "distinct" and valid else 0,
        "errors": errors,
        "warnings": warnings,
        "document": document if valid else None,
        "confirmation_token": token,
        "privacy_warning": MEDICAL_WARNING,
    }
    validate_json_document(preview, "medical_import_preview")
    return preview


def _remap_collisions(document: dict) -> tuple[dict, dict[str, str]]:
    cloned = json.loads(json.dumps(document, ensure_ascii=False, allow_nan=False))
    mapping = {}
    for model, resource in [(MedicalStudy, cloned["study"])]:
        source = resource["public_id"]
        if db.session.execute(db.select(model.id).where(model.public_id == source)).scalar_one_or_none():
            resource["public_id"] = str(uuid.uuid4())
            mapping[source] = resource["public_id"]
    for panel in cloned["panels"]:
        source = panel["public_id"]
        if db.session.execute(db.select(LabPanel.id).where(LabPanel.public_id == source)).scalar_one_or_none():
            panel["public_id"] = str(uuid.uuid4())
            mapping[source] = panel["public_id"]
        for result in panel["results"]:
            source = result["public_id"]
            if db.session.execute(db.select(LabResult.id).where(LabResult.public_id == source)).scalar_one_or_none():
                result["public_id"] = str(uuid.uuid4())
                mapping[source] = result["public_id"]
    for document_meta in cloned["attachments"]:
        source = document_meta["public_id"]
        if db.session.execute(db.select(MedicalDocument.id).where(MedicalDocument.public_id == source)).scalar_one_or_none():
            document_meta["public_id"] = str(uuid.uuid4())
            mapping[source] = document_meta["public_id"]
    return cloned, mapping


def confirm_import(user_id: int, payload: dict) -> dict:
    if set(payload) != {"document", "confirmation_token", "confirmed"} or payload.get("confirmed") is not True:
        raise MobileSyncError("confirmation_required", "La importación requiere confirmación explícita.")
    document = payload.get("document")
    if not isinstance(document, dict):
        raise MobileSyncError("invalid_request", "Falta el documento médico validado.")
    try:
        signed = _serializer().loads(payload.get("confirmation_token", ""), max_age=900)
    except BadData as error:
        raise MobileSyncError("preview_expired", "El preview cambió o venció.", 409) from error
    if signed.get("user") != user_id or signed.get("hash") != _json_hash(document):
        raise MobileSyncError("preview_changed", "El documento cambió después del preview.", 409)
    try:
        validate_json_document(document, "medical_study")
    except JsonSchemaValidationError as error:
        raise MobileSyncError("schema_error", str(error)) from error
    classification, existing = _classification(user_id, document)
    if classification == "exact_structured_duplicate" and existing is not None:
        result = {
            "schema_version": "1.0", "format": FORMAT, "state": "completed_with_skips",
            "study_public_id": existing.public_id, "created": 0, "skipped": 1,
            "duplicate_classification": classification, "uuid_mapping": {}, "warnings": [],
        }
        validate_json_document(result, "medical_import_result")
        return result
    normalized, mapping = _remap_collisions(document)
    study_data = normalized["study"]
    source = "csv_import" if signed.get("format") == "csv" else "json_import"
    create_payload = {
        "public_id": study_data["public_id"],
        "study_type": study_data["study_type"],
        "title": study_data["title"],
        "laboratory_name": study_data.get("laboratory_name"),
        "professional_name": study_data.get("professional_name"),
        "study_date": study_data["study_date"],
        "issued_date": study_data.get("issued_date"),
        "timezone": study_data.get("timezone"),
        "notes": study_data.get("notes"),
        "state": study_data["state"],
        "source": source,
        "panels": [
            {
                **{key: value for key, value in panel.items() if key not in {"revision", "results"}},
                "source": source,
                "results": [
                    {**{key: value for key, value in item.items() if key != "revision"}, "source": source}
                    for item in panel["results"]
                ],
            }
            for panel in normalized["panels"]
        ],
    }
    study = create_study(user_id, create_payload)
    for metadata in normalized["attachments"]:
        db.session.add(MedicalDocument(
            public_id=metadata["public_id"], user_id=user_id, study_id=study.id,
            uploaded_file_id=None, document_type=metadata["document_type"],
            original_filename=metadata["filename"], mime_type=metadata["mime_type"],
            size_bytes=int(metadata["size_bytes"]), sha256=metadata["sha256"],
            availability="metadata_only", source=source, revision=max(1, int(metadata["revision"])),
        ))
    _audit(user_id, study.public_id, "imported", counts={
        "panel_count": len(study.panels), "result_count": sum(len(panel.results) for panel in study.panels),
        "document_count": len(normalized["attachments"]), "revision": study.revision,
    })
    result = {
        "schema_version": "1.0", "format": FORMAT, "state": "completed",
        "study_public_id": study.public_id, "created": 1, "skipped": 0,
        "duplicate_classification": classification, "uuid_mapping": mapping,
        "warnings": ["Los documentos originales no formaban parte de esta importación."] if normalized["attachments"] else [],
    }
    validate_json_document(result, "medical_import_result")
    return result


def csv_template() -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    return output.getvalue()
