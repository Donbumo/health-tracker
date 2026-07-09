"""Standard JSON generation for assisted medical lab candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_number,
    drop_none,
)
from app.services.importers.universal_json_import_assistant import (
    MEDICAL_LAB_ALIASES,
    _normalize_key,
)


SCHEMA_NAME = "medical_lab"

LOCAL_ALIASES = {
    "laboratorio": "lab_name",
    "lab_name": "lab_name",
    "laboratory_name": "lab_name",
    "fecha": "lab_date",
    "lab_date": "lab_date",
    "date": "lab_date",
    "marcadores": "markers",
    "analitos": "markers",
    "markers": "markers",
    "marker": "name",
    "marcador": "name",
    "nombre": "name",
    "name": "name",
    "valor": "value",
    "value": "value",
    "unidad": "unit",
    "unit": "unit",
    "rango_referencia": "reference_range",
    "reference_range": "reference_range",
    "reference_text": "reference_range",
    "estado": "status",
    "status": "status",
    "notas": "notes",
    "notes": "notes",
    "codigo": "code",
    "code": "code",
    "glucosa": "glucose",
    "glucose": "glucose",
    "insulina": "insulin",
    "insulin": "insulin",
    "hba1c": "hba1c",
    "colesterol": "total_cholesterol",
    "colesterol_total": "total_cholesterol",
    "total_cholesterol": "total_cholesterol",
    "hdl": "hdl",
    "ldl": "ldl",
    "trigliceridos": "triglycerides",
    "triglycerides": "triglycerides",
    "tsh": "tsh",
    "vitamina_d": "vitamin_d",
    "vitamin_d": "vitamin_d",
    "b12": "b12",
    "ferritina": "ferritin",
    "ferritin": "ferritin",
}

MARKER_ALIASES = {
    "glucose",
    "insulin",
    "hba1c",
    "total_cholesterol",
    "hdl",
    "ldl",
    "triglycerides",
    "tsh",
    "vitamin_d",
    "b12",
    "ferritin",
}


def parent_path(path: str) -> str | None:
    marker_roots = {"marcadores", "markers", "analitos"}
    marker_suffixes = (".marcadores", ".markers", ".analitos")

    if path in marker_roots:
        return "$"

    for suffix in marker_suffixes:
        if path.endswith(suffix):
            parent = path[: -len(suffix)]
            return parent or "$"

    return None


def normalize_source_type(source_type: str) -> str:
    if source_type in {"manual_generated", "uploaded"}:
        return source_type
    return "uploaded"


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate medical_lab documents from an assisted candidate mapping.

    This function must not invent required lab or marker values.
    If required fields are missing, validation reports the missing fields.
    """

    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for record in records:
        document: dict[str, Any] = {
            "schema_version": "1.0",
            "type": "medical_lab",
            "user_id": user_id,
            "source_type": source_type,
            "markers": [],
        }
        markers_source: Any = None

        for source_field, value in record.items():
            canonical = _get_canonical(source_field, mapping)

            if canonical in MARKER_ALIASES:
                marker: dict[str, Any] = {"name": canonical}
                if isinstance(value, dict):
                    for marker_field, marker_value in value.items():
                        _apply_marker_field(
                            marker,
                            _get_canonical(marker_field, mapping),
                            marker_value,
                        )
                else:
                    marker["value"] = _number_or_raw(value)
                document["markers"].append(drop_none(marker))
                continue

            if canonical == "lab_date":
                document["date"] = str(value)
            elif canonical == "lab_name":
                document["laboratory_name"] = str(value)
            elif canonical == "markers":
                markers_source = value
            elif canonical == "notes":
                document["notes"] = str(value)

        if isinstance(markers_source, list):
            for marker_item in markers_source:
                if not isinstance(marker_item, dict):
                    continue

                marker: dict[str, Any] = {}
                for source_field, value in marker_item.items():
                    canonical = _get_canonical(source_field, mapping)
                    _apply_marker_field(marker, canonical, value)

                if marker:
                    document["markers"].append(drop_none(marker))

        document = drop_none(document)
        documents.append(document)

    return documents, warnings


def _get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return mapping[key]
    normalized = _normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]
    return MEDICAL_LAB_ALIASES.get(normalized)


def _number_or_raw(value: Any) -> Any:
    number = coerce_number(value)
    if number is None:
        return value
    return float(number)


def _apply_marker_field(
    marker: dict[str, Any],
    canonical: str | None,
    value: Any,
) -> None:
    if not canonical:
        return
    if canonical == "name":
        marker["name"] = str(value)
    elif canonical == "value":
        marker["value"] = _number_or_raw(value)
    elif canonical == "unit":
        marker["unit"] = str(value)
    elif canonical == "reference_range":
        marker["reference_text"] = str(value)
    elif canonical == "status":
        marker["status"] = str(value).lower()
    elif canonical == "notes":
        marker["notes"] = str(value)
    elif canonical == "code":
        marker["code"] = str(value)
