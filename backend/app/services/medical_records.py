from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    LabPanel,
    LabResult,
    LabResultRevision,
    MedicalAuditEvent,
    MedicalDocument,
    MedicalDuplicateCandidate,
    MedicalStudy,
    MedicalStudySource,
)
from app.models.medical_records import (
    COMPARATORS,
    SOURCE_STATUSES,
    STUDY_STATES,
    STUDY_TYPES,
    VALUE_TYPES,
)
from app.services.mobile_sync import MobileSyncError, rfc3339


MEDICAL_WARNING = "Los estudios y resultados pueden contener información médica sensible."
RANGE_NOTICE = "Según el rango incluido en este informe."
COMPARABILITY_NOTICE = "Unidades o métodos no comparables"

MARKER_CATALOG_VERSION = "1.0"
MARKER_CATALOG = (
    ("glucose", "Glucosa", ("glucose", "glucosa"), ("metabolic",), ("numeric",)),
    ("hba1c", "HbA1c", ("hba1c", "hemoglobina glucosilada"), ("metabolic",), ("numeric",)),
    ("total_cholesterol", "Colesterol total", ("total cholesterol", "colesterol total"), ("lipids",), ("numeric",)),
    ("ldl", "LDL", ("ldl",), ("lipids",), ("numeric",)),
    ("hdl", "HDL", ("hdl",), ("lipids",), ("numeric",)),
    ("triglycerides", "Triglicéridos", ("triglycerides", "triglicéridos"), ("lipids",), ("numeric",)),
    ("creatinine", "Creatinina", ("creatinine", "creatinina"), ("chemistry",), ("numeric",)),
    ("alt", "ALT", ("alt", "alanine aminotransferase"), ("enzymes",), ("numeric",)),
    ("ast", "AST", ("ast", "aspartate aminotransferase"), ("enzymes",), ("numeric",)),
    ("tsh", "TSH", ("tsh",), ("hormones",), ("numeric",)),
    ("vitamin_d", "Vitamina D", ("vitamin d", "vitamina d"), ("vitamins",), ("numeric",)),
    ("vitamin_b12", "Vitamina B12", ("vitamin b12", "vitamina b12"), ("vitamins",), ("numeric",)),
    ("ferritin", "Ferritina", ("ferritin", "ferritina"), ("iron",), ("numeric",)),
)
CATALOG_KEYS = {item[0] for item in MARKER_CATALOG}

# Deliberately small. These are dimensional scale conversions only; there is no
# molar/mass, analyte-specific or clinical conversion.
UNIT_CONVERSIONS = {
    "kg": {"canonical_unit": "g", "factor": Decimal("1000"), "precision": 6},
    "g": {"canonical_unit": "g", "factor": Decimal("1"), "precision": 6},
    "mg": {"canonical_unit": "g", "factor": Decimal("0.001"), "precision": 9},
    "l": {"canonical_unit": "mL", "factor": Decimal("1000"), "precision": 6},
    "ml": {"canonical_unit": "mL", "factor": Decimal("1"), "precision": 6},
    "g/l": {"canonical_unit": "mg/L", "factor": Decimal("1000"), "precision": 6},
    "mg/l": {"canonical_unit": "mg/L", "factor": Decimal("1"), "precision": 6},
    "°c": {"canonical_unit": "°C", "factor": Decimal("1"), "precision": 4},
}
UNIT_CONVERSION_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(value, field="public_id") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise MobileSyncError("invalid_id", f"{field} debe ser un UUID válido.") from error


def _date(value, field: str, *, optional=False) -> date | None:
    if optional and value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise MobileSyncError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _text(value, field: str, maximum: int, *, optional=False) -> str | None:
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str):
        raise MobileSyncError("invalid_request", f"{field} debe ser texto.")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise MobileSyncError("invalid_request", f"{field} no es válido.")
    return normalized


def _decimal(value, field: str, *, optional=False) -> Decimal | None:
    if optional and value in (None, ""):
        return None
    if isinstance(value, bool):
        raise MobileSyncError("invalid_number", f"{field} debe ser numérico.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MobileSyncError("invalid_number", f"{field} debe ser numérico.") from error
    if not parsed.is_finite() or abs(parsed) > Decimal("1e20"):
        raise MobileSyncError("invalid_number", f"{field} no es un número finito válido.")
    return parsed


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _source(value) -> str:
    normalized = str(value or "manual").strip().casefold().replace("-", "_")
    if normalized not in {"manual", "mobile", "json_import", "csv_import", "portable_import"}:
        raise MobileSyncError("invalid_source", "La procedencia no está soportada.")
    return normalized


def _timezone(value) -> str | None:
    if value in (None, ""):
        return None
    normalized = _text(value, "timezone", 64)
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise MobileSyncError("invalid_timezone", "timezone debe ser una zona IANA válida.") from error
    return normalized


def _base_revision(current: int, value) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MobileSyncError("base_revision_required", "Se requiere base_revision.")
    if value != current:
        raise MobileSyncError(
            "revision_conflict",
            "El recurso cambió en el servidor.",
            409,
            {"server_revision": current, "conflict_code": "stale_revision"},
        )


def _canonical_unit(unit: str | None) -> tuple[str | None, Decimal | None]:
    if not unit:
        return None, None
    spec = UNIT_CONVERSIONS.get(unit.strip().casefold())
    if not spec:
        return None, None
    return spec["canonical_unit"], spec["factor"]


def _derived_range_status(
    value_type: str,
    numeric_value: Decimal | None,
    lower: Decimal | None,
    upper: Decimal | None,
    comparator: str,
) -> str:
    if (
        value_type != "numeric"
        or numeric_value is None
        or (lower is None and upper is None)
        or comparator not in {"equal", "none"}
    ):
        return "not_computable"
    if lower is not None and numeric_value < lower:
        return "below_reported_range"
    if upper is not None and numeric_value > upper:
        return "above_reported_range"
    return "within_reported_range"


def marker_catalog(query: str | None = None) -> list[dict]:
    normalized = (query or "").strip().casefold()
    rows = []
    for key, name, aliases, categories, value_types in MARKER_CATALOG:
        if normalized and normalized not in key and not any(normalized in item.casefold() for item in (name, *aliases)):
            continue
        rows.append({
            "canonical_key": key,
            "display_name": name,
            "aliases": list(aliases),
            "categories": list(categories),
            "observed_units": [],
            "allowed_value_types": list(value_types),
            "active": True,
            "version": MARKER_CATALOG_VERSION,
        })
    return rows


def conversion_catalog() -> list[dict]:
    return [
        {
            "source_unit": source,
            "canonical_unit": spec["canonical_unit"],
            "factor": _number(spec["factor"]),
            "precision": spec["precision"],
            "version": UNIT_CONVERSION_VERSION,
        }
        for source, spec in sorted(UNIT_CONVERSIONS.items())
    ]


def _audit(
    user_id: int,
    study_public_id: str,
    action: str,
    *,
    entity_type="study",
    entity_public_id: str | None = None,
    counts: dict | None = None,
) -> None:
    # Only allow non-clinical diagnostics. Never place values, units, names,
    # notes, file names, hashes or ranges in this table.
    safe = {}
    for key, value in (counts or {}).items():
        if key in {"panel_count", "result_count", "document_count", "revision", "state"}:
            safe[key] = value
    db.session.add(MedicalAuditEvent(
        user_id=user_id,
        study_public_id=study_public_id,
        entity_type=entity_type,
        entity_public_id=entity_public_id,
        action=action,
        details_json=safe,
    ))


def _result_snapshot(row: LabResult) -> dict:
    return {
        "display_name": row.display_name,
        "canonical_key": row.canonical_key,
        "value_type": row.value_type,
        "original_value": row.original_value,
        "numeric_value": _number(row.numeric_value),
        "comparator": row.comparator,
        "original_unit": row.original_unit,
        "canonical_unit": row.canonical_unit,
        "reference_lower": _number(row.reference_lower),
        "reference_upper": _number(row.reference_upper),
        "reference_text": row.reference_text,
        "source_status": row.source_status,
        "derived_range_status": row.derived_range_status,
        "method": row.method,
        "specimen": row.specimen,
        "notes": row.notes,
        "display_order": row.display_order,
    }


def serialize_revision(row: LabResultRevision) -> dict:
    return {
        "public_id": row.public_id,
        "revision": row.revision,
        "snapshot": row.snapshot_json,
        "correction_reason": row.correction_reason,
        "source": row.source,
        "created_at": rfc3339(row.created_at),
    }


def serialize_result(row: LabResult, *, include_revisions=False) -> dict:
    result = {
        "public_id": row.public_id,
        "panel_public_id": row.panel.public_id,
        "display_name": row.display_name,
        "canonical_key": row.canonical_key,
        "value_type": row.value_type,
        "original_value": row.original_value,
        "numeric_value": _number(row.numeric_value),
        "comparator": row.comparator,
        "original_unit": row.original_unit,
        "canonical_unit": row.canonical_unit,
        "reference_lower": _number(row.reference_lower),
        "reference_upper": _number(row.reference_upper),
        "reference_text": row.reference_text,
        "source_status": row.source_status,
        "derived_range_status": row.derived_range_status,
        "range_notice": RANGE_NOTICE,
        "method": row.method,
        "specimen": row.specimen,
        "notes": row.notes,
        "display_order": row.display_order,
        "revision": row.revision,
        "source": row.source,
        "created_at": rfc3339(row.created_at),
        "updated_at": rfc3339(row.updated_at),
    }
    if include_revisions:
        result["revisions"] = [serialize_revision(item) for item in row.revisions]
    return result


def serialize_panel(row: LabPanel, *, include_results=True) -> dict:
    result = {
        "public_id": row.public_id,
        "name": row.name,
        "display_order": row.display_order,
        "source": row.source,
        "revision": row.revision,
        "result_count": len(row.results),
        "created_at": rfc3339(row.created_at),
        "updated_at": rfc3339(row.updated_at),
    }
    if include_results:
        result["results"] = [serialize_result(item, include_revisions=True) for item in row.results]
    return result


def serialize_document(row: MedicalDocument) -> dict:
    return {
        "public_id": row.public_id,
        "study_public_id": row.study.public_id,
        "document_type": row.document_type,
        "filename": row.original_filename,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "availability": row.availability,
        "source": row.source,
        "revision": row.revision,
        "created_at": rfc3339(row.created_at),
    }


def serialize_study(row: MedicalStudy, *, detail=False) -> dict:
    value = {
        "public_id": row.public_id,
        "study_type": row.study_type,
        "title": row.title,
        "laboratory_name": row.laboratory_name,
        "professional_name": row.professional_name,
        "study_date": row.study_date.isoformat(),
        "issued_date": row.issued_date.isoformat() if row.issued_date else None,
        "timezone": row.timezone,
        "notes": row.notes,
        "state": row.state,
        "source": row.source,
        "revision": row.revision,
        "panel_count": len(row.panels),
        "result_count": sum(len(panel.results) for panel in row.panels),
        "document_count": len(row.documents),
        "created_at": rfc3339(row.created_at),
        "updated_at": rfc3339(row.updated_at),
        "privacy_warning": MEDICAL_WARNING,
    }
    if detail:
        value["panels"] = [serialize_panel(panel) for panel in row.panels]
        value["documents"] = [serialize_document(document) for document in row.documents]
        value["sources"] = [{
            "public_id": source.public_id,
            "source_type": source.source_type,
            "source_reference": source.source_reference,
            "metadata": source.metadata_json or {},
            "created_at": rfc3339(source.created_at),
        } for source in row.sources]
    return value


def _study_loaders():
    return (
        selectinload(MedicalStudy.panels).selectinload(LabPanel.results).selectinload(LabResult.revisions),
        selectinload(MedicalStudy.documents).selectinload(MedicalDocument.uploaded_file),
        selectinload(MedicalStudy.sources),
    )


def owned_study(user_id: int, public_id: str, *, lock=False) -> MedicalStudy:
    statement = db.select(MedicalStudy).options(*_study_loaders()).where(
        MedicalStudy.user_id == user_id,
        MedicalStudy.public_id == _uuid(public_id),
    )
    if lock:
        statement = statement.with_for_update()
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None:
        raise MobileSyncError("not_found", "Estudio no encontrado.", 404)
    return row


def owned_result(user_id: int, public_id: str, *, lock=False) -> LabResult:
    statement = db.select(LabResult).options(
        selectinload(LabResult.panel).selectinload(LabPanel.study),
        selectinload(LabResult.revisions),
    ).where(LabResult.user_id == user_id, LabResult.public_id == _uuid(public_id))
    if lock:
        statement = statement.with_for_update()
    row = db.session.execute(statement).scalar_one_or_none()
    if row is None or row.panel.study.user_id != user_id:
        raise MobileSyncError("not_found", "Resultado no encontrado.", 404)
    return row


def owned_document(user_id: int, public_id: str) -> MedicalDocument:
    row = db.session.execute(
        db.select(MedicalDocument)
        .options(selectinload(MedicalDocument.study), selectinload(MedicalDocument.uploaded_file))
        .where(MedicalDocument.user_id == user_id, MedicalDocument.public_id == _uuid(public_id))
    ).scalar_one_or_none()
    if row is None or row.study.user_id != user_id:
        raise MobileSyncError("not_found", "Documento no encontrado.", 404)
    return row


def list_studies(
    user_id: int,
    *,
    limit=50,
    offset=0,
    state: str | None = None,
    study_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit not in range(1, 101):
        raise MobileSyncError("invalid_pagination", "limit debe estar entre 1 y 100.")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 100_000:
        raise MobileSyncError("invalid_pagination", "offset no es válido.")
    statement = db.select(MedicalStudy).options(*_study_loaders()).where(MedicalStudy.user_id == user_id)
    count_statement = db.select(db.func.count(MedicalStudy.id)).where(MedicalStudy.user_id == user_id)
    conditions = []
    if state:
        if state not in STUDY_STATES:
            raise MobileSyncError("invalid_filter", "state no es válido.")
        conditions.append(MedicalStudy.state == state)
    if study_type:
        if study_type not in STUDY_TYPES:
            raise MobileSyncError("invalid_filter", "study_type no es válido.")
        conditions.append(MedicalStudy.study_type == study_type)
    if date_from:
        conditions.append(MedicalStudy.study_date >= date_from)
    if date_to:
        conditions.append(MedicalStudy.study_date <= date_to)
    for condition in conditions:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    total = db.session.execute(count_statement).scalar_one()
    rows = db.session.execute(
        statement.order_by(MedicalStudy.study_date.desc(), MedicalStudy.public_id)
        .offset(offset).limit(limit)
    ).scalars().all()
    return {
        "items": [serialize_study(row) for row in rows],
        "pagination": {"limit": limit, "offset": offset, "total": total, "has_more": offset + len(rows) < total},
    }


def _study_values(payload: dict, *, creating: bool) -> dict:
    fields = {
        "public_id", "study_type", "title", "laboratory_name", "professional_name",
        "study_date", "issued_date", "timezone", "notes", "state", "source",
        "base_revision", "panels",
    }
    if set(payload) - fields:
        raise MobileSyncError("invalid_request", "El estudio contiene campos no reconocidos.")
    if creating and not {"study_type", "title", "study_date"} <= set(payload):
        raise MobileSyncError("invalid_request", "Faltan campos requeridos del estudio.")
    values = {}
    if "study_type" in payload:
        if payload["study_type"] not in STUDY_TYPES:
            raise MobileSyncError("invalid_study_type", "El tipo de estudio no está soportado.")
        values["study_type"] = payload["study_type"]
    if "title" in payload:
        values["title"] = _text(payload["title"], "title", 240)
    for field, maximum in (("laboratory_name", 200), ("professional_name", 200), ("notes", 5000)):
        if field in payload:
            values[field] = _text(payload[field], field, maximum, optional=True)
    if "study_date" in payload:
        values["study_date"] = _date(payload["study_date"], "study_date")
    if "issued_date" in payload:
        values["issued_date"] = _date(payload["issued_date"], "issued_date", optional=True)
    if "timezone" in payload:
        values["timezone"] = _timezone(payload["timezone"])
    if "state" in payload:
        if payload["state"] not in STUDY_STATES:
            raise MobileSyncError("invalid_state", "El estado del estudio no es válido.")
        values["state"] = payload["state"]
    elif creating:
        values["state"] = "draft"
    if "source" in payload:
        values["source"] = _source(payload["source"])
    elif creating:
        values["source"] = "mobile"
    issued = values.get("issued_date")
    study_day = values.get("study_date")
    if issued and study_day and issued < study_day:
        raise MobileSyncError("invalid_date_range", "issued_date no puede ser anterior a study_date.")
    return values


def create_study(user_id: int, payload: dict) -> MedicalStudy:
    values = _study_values(payload, creating=True)
    public_id = _uuid(payload.get("public_id") or uuid.uuid4())
    if db.session.execute(db.select(MedicalStudy.id).where(MedicalStudy.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El identificador del estudio no está disponible.", 409)
    panels = payload.get("panels") or []
    if not isinstance(panels, list) or len(panels) > 50:
        raise MobileSyncError("invalid_request", "panels no es válido.")
    if panels and values["study_type"] != "laboratory":
        raise MobileSyncError("invalid_study_type", "Solo laboratory admite resultados estructurados.")
    row = MedicalStudy(public_id=public_id, user_id=user_id, **values)
    db.session.add(row)
    db.session.flush()
    row.sources.append(MedicalStudySource(
        user_id=user_id,
        source_type=row.source,
        source_reference=None,
        metadata_json={"schema_version": "1.0"},
    ))
    for index, panel_payload in enumerate(panels):
        _create_panel(row, panel_payload, index)
    _refresh_fingerprints(row)
    _audit(user_id, row.public_id, "created", counts={
        "panel_count": len(row.panels), "result_count": sum(len(item.results) for item in row.panels),
        "revision": row.revision, "state": row.state,
    })
    db.session.flush()
    return owned_study(user_id, row.public_id)


def patch_study(user_id: int, public_id: str, payload: dict) -> MedicalStudy:
    row = owned_study(user_id, public_id, lock=True)
    _base_revision(row.revision, payload.get("base_revision"))
    values = _study_values(payload, creating=False)
    if "panels" in payload:
        raise MobileSyncError("invalid_request", "Los paneles se editan mediante resultados.")
    merged_study_date = values.get("study_date", row.study_date)
    merged_issued = values.get("issued_date", row.issued_date)
    if merged_issued and merged_issued < merged_study_date:
        raise MobileSyncError("invalid_date_range", "issued_date no puede ser anterior a study_date.")
    if values.get("study_type", row.study_type) != "laboratory" and row.panels:
        raise MobileSyncError("invalid_study_type", "No se puede cambiar el tipo mientras existan resultados estructurados.", 409)
    for key, value in values.items():
        setattr(row, key, value)
    row.revision += 1
    row.updated_at = utcnow()
    _refresh_fingerprints(row)
    _audit(user_id, row.public_id, "edited", counts={"revision": row.revision, "state": row.state})
    db.session.flush()
    return row


def archive_study(user_id: int, public_id: str, payload: dict) -> MedicalStudy:
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere únicamente base_revision.")
    row = owned_study(user_id, public_id, lock=True)
    _base_revision(row.revision, payload["base_revision"])
    row.state = "archived"
    row.revision += 1
    row.updated_at = utcnow()
    _audit(user_id, row.public_id, "archived", counts={"revision": row.revision, "state": row.state})
    db.session.flush()
    return row


def _panel_payload(value, default_order: int) -> tuple[str, str, int]:
    if not isinstance(value, dict) or set(value) - {"public_id", "name", "display_order", "results", "source"}:
        raise MobileSyncError("invalid_request", "El panel no es válido.")
    name = _text(value.get("name", "Panel"), "panel.name", 200)
    public_id = _uuid(value.get("public_id") or uuid.uuid4(), "panel.public_id")
    order = value.get("display_order", default_order)
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10_000:
        raise MobileSyncError("invalid_request", "panel.display_order no es válido.")
    return public_id, name, order


def _create_panel(study: MedicalStudy, payload: dict, default_order: int) -> LabPanel:
    public_id, name, order = _panel_payload(payload, default_order)
    if db.session.execute(db.select(LabPanel.id).where(LabPanel.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El identificador del panel no está disponible.", 409)
    if any(panel.display_order == order for panel in study.panels):
        order = max((panel.display_order for panel in study.panels), default=-1) + 1
    panel = LabPanel(
        public_id=public_id, user_id=study.user_id, name=name, display_order=order,
        source=_source(payload.get("source") or study.source),
    )
    study.panels.append(panel)
    db.session.flush()
    results = payload.get("results") or []
    if not isinstance(results, list) or len(results) > 500:
        raise MobileSyncError("invalid_request", "panel.results no es válido.")
    for index, result_payload in enumerate(results):
        _append_result(panel, result_payload, index)
    return panel


def _result_values(payload: dict, *, creating: bool) -> dict:
    fields = {
        "public_id", "panel_public_id", "panel_name", "display_name", "canonical_key",
        "value_type", "original_value", "numeric_value", "comparator", "original_unit",
        "reference_lower", "reference_upper", "reference_text", "source_status",
        "method", "specimen", "notes", "display_order", "source", "base_revision",
        "correction_reason",
    }
    if not isinstance(payload, dict) or set(payload) - fields:
        raise MobileSyncError("invalid_request", "El resultado contiene campos no reconocidos.")
    required = {"display_name", "value_type", "original_value"}
    if creating and not required <= set(payload):
        raise MobileSyncError("invalid_request", "Faltan campos requeridos del resultado.")
    values = {}
    if "display_name" in payload:
        values["display_name"] = _text(payload["display_name"], "display_name", 200)
    if "canonical_key" in payload:
        key = _text(payload["canonical_key"], "canonical_key", 100, optional=True)
        if key is not None and not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", key):
            raise MobileSyncError("invalid_marker", "canonical_key no es válida.")
        values["canonical_key"] = key
    if "value_type" in payload:
        if payload["value_type"] not in VALUE_TYPES:
            raise MobileSyncError("invalid_value_type", "value_type no está soportado.")
        values["value_type"] = payload["value_type"]
    if "original_value" in payload:
        values["original_value"] = _text(str(payload["original_value"]), "original_value", 500)
    if "comparator" in payload:
        if payload["comparator"] not in COMPARATORS:
            raise MobileSyncError("invalid_comparator", "comparator no está soportado.")
        values["comparator"] = payload["comparator"]
    elif creating:
        values["comparator"] = "none"
    if "original_unit" in payload:
        values["original_unit"] = _text(payload["original_unit"], "original_unit", 100, optional=True)
    for field in ("reference_text", "method", "specimen", "notes"):
        if field in payload:
            values[field] = _text(payload[field], field, 2000 if field == "notes" else 500 if field == "reference_text" else 200, optional=True)
    for field in ("reference_lower", "reference_upper"):
        if field in payload:
            values[field] = _decimal(payload[field], field, optional=True)
    if "source_status" in payload:
        if payload["source_status"] not in SOURCE_STATUSES:
            raise MobileSyncError("invalid_source_status", "source_status no está soportado.")
        values["source_status"] = payload["source_status"]
    elif creating:
        values["source_status"] = "not_provided"
    if "display_order" in payload:
        order = payload["display_order"]
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 100_000:
            raise MobileSyncError("invalid_request", "display_order no es válido.")
        values["display_order"] = order
    if "source" in payload:
        values["source"] = _source(payload["source"])
    elif creating:
        values["source"] = "mobile"
    value_type = values.get("value_type")
    original = values.get("original_value")
    if "numeric_value" in payload:
        values["numeric_value"] = _decimal(payload["numeric_value"], "numeric_value", optional=True)
    elif value_type == "numeric" and original is not None:
        try:
            values["numeric_value"] = _decimal(original, "original_value")
        except MobileSyncError:
            raise MobileSyncError("numeric_value_required", "numeric_value es requerido cuando el valor original no es un número exacto.")
    if value_type == "numeric" and values.get("numeric_value") is None:
        raise MobileSyncError("numeric_value_required", "Los resultados numéricos requieren numeric_value.")
    if value_type and value_type != "numeric" and values.get("numeric_value") is not None:
        raise MobileSyncError("invalid_number", "Solo value_type numeric admite numeric_value.")
    lower, upper = values.get("reference_lower"), values.get("reference_upper")
    if lower is not None and upper is not None and lower > upper:
        raise MobileSyncError("invalid_range", "reference_lower no puede superar reference_upper.")
    return values


def _append_result(panel: LabPanel, payload: dict, default_order: int) -> LabResult:
    values = _result_values(payload, creating=True)
    public_id = _uuid(payload.get("public_id") or uuid.uuid4())
    if db.session.execute(db.select(LabResult.id).where(LabResult.public_id == public_id)).scalar_one_or_none():
        raise MobileSyncError("conflict", "El identificador del resultado no está disponible.", 409)
    order = values.pop("display_order", default_order)
    if any(result.display_order == order for result in panel.results):
        order = max((result.display_order for result in panel.results), default=-1) + 1
    canonical_unit, _ = _canonical_unit(values.get("original_unit"))
    derived = _derived_range_status(
        values["value_type"], values.get("numeric_value"),
        values.get("reference_lower"), values.get("reference_upper"), values["comparator"],
    )
    row = LabResult(
        public_id=public_id,
        user_id=panel.user_id,
        display_order=order,
        canonical_unit=canonical_unit,
        derived_range_status=derived,
        **values,
    )
    panel.results.append(row)
    db.session.flush()
    row.revisions.append(LabResultRevision(
        user_id=row.user_id,
        revision=1,
        snapshot_json=_result_snapshot(row),
        source=row.source,
    ))
    return row


def create_result(user_id: int, study_public_id: str, payload: dict) -> LabResult:
    study = owned_study(user_id, study_public_id, lock=True)
    if study.study_type != "laboratory":
        raise MobileSyncError("invalid_study_type", "Solo laboratory admite resultados estructurados.")
    panel = None
    if payload.get("panel_public_id"):
        panel = next((item for item in study.panels if item.public_id == _uuid(payload["panel_public_id"], "panel_public_id")), None)
        if panel is None:
            raise MobileSyncError("not_found", "Panel no encontrado.", 404)
    if panel is None:
        panel_name = payload.get("panel_name") or "Resultados"
        panel = _create_panel(study, {"name": panel_name, "results": [], "source": payload.get("source")}, len(study.panels))
    row = _append_result(panel, payload, len(panel.results))
    panel.revision += 1
    panel.updated_at = utcnow()
    study.revision += 1
    study.updated_at = utcnow()
    _refresh_fingerprints(study)
    _audit(user_id, study.public_id, "result_added", entity_type="result", entity_public_id=row.public_id,
           counts={"result_count": sum(len(item.results) for item in study.panels), "revision": study.revision})
    db.session.flush()
    return row


def patch_result(user_id: int, public_id: str, payload: dict) -> LabResult:
    row = owned_result(user_id, public_id, lock=True)
    _base_revision(row.revision, payload.get("base_revision"))
    values = _result_values(payload, creating=False)
    merged = _result_snapshot(row)
    merged.update({key: _number(value) if isinstance(value, Decimal) else value for key, value in values.items()})
    value_type = values.get("value_type", row.value_type)
    numeric = values.get("numeric_value", row.numeric_value)
    if value_type == "numeric" and numeric is None:
        raise MobileSyncError("numeric_value_required", "Los resultados numéricos requieren numeric_value.")
    if value_type != "numeric" and numeric is not None:
        numeric = None
        values["numeric_value"] = None
    lower = values.get("reference_lower", row.reference_lower)
    upper = values.get("reference_upper", row.reference_upper)
    if lower is not None and upper is not None and lower > upper:
        raise MobileSyncError("invalid_range", "reference_lower no puede superar reference_upper.")
    comparator = values.get("comparator", row.comparator)
    for key, value in values.items():
        setattr(row, key, value)
    row.numeric_value = numeric
    row.canonical_unit = _canonical_unit(row.original_unit)[0]
    row.derived_range_status = _derived_range_status(value_type, numeric, lower, upper, comparator)
    row.revision += 1
    row.updated_at = utcnow()
    reason = _text(payload.get("correction_reason"), "correction_reason", 500, optional=True)
    row.revisions.append(LabResultRevision(
        user_id=user_id,
        revision=row.revision,
        snapshot_json=_result_snapshot(row),
        correction_reason=reason,
        source=row.source,
    ))
    study = row.panel.study
    row.panel.revision += 1
    row.panel.updated_at = utcnow()
    study.revision += 1
    study.updated_at = utcnow()
    _refresh_fingerprints(study)
    _audit(user_id, study.public_id, "result_corrected", entity_type="result", entity_public_id=row.public_id,
           counts={"revision": row.revision})
    db.session.flush()
    return row


def delete_result(user_id: int, public_id: str, payload: dict) -> dict:
    if set(payload) != {"base_revision"}:
        raise MobileSyncError("invalid_request", "Se requiere únicamente base_revision.")
    row = owned_result(user_id, public_id, lock=True)
    _base_revision(row.revision, payload["base_revision"])
    study = row.panel.study
    panel = row.panel
    result_public_id = row.public_id
    db.session.delete(row)
    db.session.flush()
    panel.revision += 1
    panel.updated_at = utcnow()
    study.revision += 1
    study.updated_at = utcnow()
    _refresh_fingerprints(study)
    _audit(user_id, study.public_id, "result_removed", entity_type="result", entity_public_id=result_public_id,
           counts={"revision": study.revision})
    return {"public_id": result_public_id, "deleted": True, "study_revision": study.revision}


def _panel_fingerprint(panel: LabPanel) -> str:
    data = [{
        "name": result.display_name.casefold(),
        "key": result.canonical_key,
        "type": result.value_type,
        "value": result.original_value,
        "unit": result.original_unit,
        "lower": _number(result.reference_lower),
        "upper": _number(result.reference_upper),
        "text": result.reference_text,
        "method": result.method,
    } for result in sorted(panel.results, key=lambda item: (item.display_order, item.public_id))]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _refresh_fingerprints(study: MedicalStudy) -> None:
    for panel in study.panels:
        panel.fingerprint = _panel_fingerprint(panel)
    if study.study_type != "laboratory" or not study.panels:
        study.structured_fingerprint = None
        return
    payload = {
        "date": study.study_date.isoformat(),
        "laboratory": (study.laboratory_name or "").strip().casefold(),
        "panels": [panel.fingerprint for panel in sorted(study.panels, key=lambda item: item.display_order)],
    }
    study.structured_fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    db.session.flush()
    other = db.session.execute(db.select(MedicalStudy).where(
        MedicalStudy.user_id == study.user_id,
        MedicalStudy.id != study.id,
        MedicalStudy.structured_fingerprint == study.structured_fingerprint,
    ).limit(1)).scalar_one_or_none()
    if other is None:
        return
    left, right = sorted((study.id, other.id))
    exists = db.session.execute(db.select(MedicalDuplicateCandidate.id).where(
        MedicalDuplicateCandidate.user_id == study.user_id,
        MedicalDuplicateCandidate.left_study_id == left,
        MedicalDuplicateCandidate.right_study_id == right,
    )).scalar_one_or_none()
    if exists is None:
        db.session.add(MedicalDuplicateCandidate(
            user_id=study.user_id,
            left_study_id=left,
            right_study_id=right,
            classification="exact_structured_duplicate",
            evidence_json={"fingerprint_match": True},
        ))


def study_results(user_id: int, public_id: str) -> dict:
    study = owned_study(user_id, public_id)
    return {
        "study_public_id": study.public_id,
        "panels": [serialize_panel(panel) for panel in study.panels],
        "total": sum(len(panel.results) for panel in study.panels),
        "range_notice": RANGE_NOTICE,
    }


def _period_start(period: str | None) -> date | None:
    if not period or period == "all":
        return None
    days = {"30d": 30, "90d": 90, "180d": 180, "1y": 365}.get(period)
    if days is None:
        raise MobileSyncError("invalid_period", "El periodo no está soportado.")
    return date.today() - timedelta(days=days - 1)


def lab_history(
    user_id: int,
    canonical_key: str,
    *,
    period: str | None = None,
    laboratory: str | None = None,
    unit: str | None = None,
    method: str | None = None,
    source: str | None = None,
    study_type: str | None = None,
) -> dict:
    key = _text(canonical_key, "canonical_key", 100)
    if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", key):
        raise MobileSyncError("invalid_marker", "canonical_key no es válida.")
    statement = db.select(LabResult).options(
        selectinload(LabResult.panel).selectinload(LabPanel.study)
    ).join(LabPanel).join(MedicalStudy).where(
        LabResult.user_id == user_id,
        LabPanel.user_id == user_id,
        MedicalStudy.user_id == user_id,
        LabResult.canonical_key == key,
    )
    start = _period_start(period)
    if start:
        statement = statement.where(MedicalStudy.study_date >= start)
    if laboratory:
        statement = statement.where(MedicalStudy.laboratory_name == laboratory)
    if unit:
        statement = statement.where(LabResult.original_unit == unit)
    if method:
        statement = statement.where(LabResult.method == method)
    if source:
        statement = statement.where(LabResult.source == _source(source))
    if study_type:
        if study_type not in STUDY_TYPES:
            raise MobileSyncError("invalid_filter", "study_type no es válido.")
        statement = statement.where(MedicalStudy.study_type == study_type)
    rows = db.session.execute(
        statement.order_by(MedicalStudy.study_date, LabResult.public_id)
    ).scalars().all()

    points = []
    baseline_unit = None
    baseline_method = None
    comparable = True
    previous = None
    for row in rows:
        canonical_unit, factor = _canonical_unit(row.original_unit)
        normalized_unit = canonical_unit or row.original_unit
        normalized_value = row.numeric_value * factor if row.numeric_value is not None and factor is not None else row.numeric_value
        row_comparable = row.value_type == "numeric" and row.numeric_value is not None
        if baseline_unit is None and row_comparable:
            baseline_unit = normalized_unit
            baseline_method = row.method
        elif row_comparable and (normalized_unit != baseline_unit or row.method != baseline_method):
            row_comparable = False
        comparable = comparable and row_comparable
        absolute_change = None
        percentage_change = None
        elapsed_days = None
        if previous is not None and row_comparable and previous["comparable"]:
            absolute_change = normalized_value - previous["normalized_value"]
            if previous["normalized_value"] != 0:
                percentage_change = absolute_change / previous["normalized_value"] * Decimal("100")
            elapsed_days = (row.panel.study.study_date - previous["date"]).days
        point = {
            "result": serialize_result(row),
            "study_public_id": row.panel.study.public_id,
            "study_date": row.panel.study.study_date.isoformat(),
            "laboratory_name": row.panel.study.laboratory_name,
            "normalized_value": _number(normalized_value) if row_comparable else None,
            "normalized_unit": normalized_unit if row_comparable else None,
            "comparable": row_comparable,
            "absolute_change": _number(absolute_change),
            "percentage_change": _number(percentage_change),
            "elapsed_days": elapsed_days,
        }
        points.append(point)
        previous = {"normalized_value": normalized_value, "date": row.panel.study.study_date, "comparable": row_comparable}
    return {
        "canonical_key": key,
        "count": len(points),
        "points": points,
        "series_comparable": bool(points) and comparable,
        "comparison_notice": None if (points and comparable) else COMPARABILITY_NOTICE,
        "range_notice": RANGE_NOTICE,
        "summary": f"{len(points)} resultados registrados",
        "unit_conversion_version": UNIT_CONVERSION_VERSION,
    }


def duplicates_for_study(user_id: int, study: MedicalStudy) -> list[dict]:
    rows = db.session.execute(db.select(MedicalDuplicateCandidate).where(
        MedicalDuplicateCandidate.user_id == user_id,
        db.or_(
            MedicalDuplicateCandidate.left_study_id == study.id,
            MedicalDuplicateCandidate.right_study_id == study.id,
        ),
    ).order_by(MedicalDuplicateCandidate.created_at)).scalars().all()
    return [{
        "public_id": row.public_id,
        "classification": row.classification,
        "resolution": row.resolution,
        "evidence": row.evidence_json,
        "created_at": rfc3339(row.created_at),
    } for row in rows]
