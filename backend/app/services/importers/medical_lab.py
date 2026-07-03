from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import MedicalLabReport, MedicalLabResult, UploadedFile
from app.services.files import mark_import_status
from app.services.importers.base import ImporterError, load_json_source
from app.services.validation import JsonSchemaValidationError, validate_json_document


class MedicalLabImportError(ValueError):
    pass


def _existing_report(source_file_id: int, user_id: int) -> MedicalLabReport | None:
    return db.session.execute(
        db.select(MedicalLabReport).where(
            MedicalLabReport.source_file_id == source_file_id,
            MedicalLabReport.user_id == user_id,
        )
    ).scalar_one_or_none()


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MedicalLabImportError(f"{field} must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _result_from_marker(
    marker: dict,
    *,
    user_id: int,
) -> MedicalLabResult:
    raw_value = marker["value"]
    numeric_value = None
    text_value = None
    if isinstance(raw_value, (int, float)):
        numeric_value = Decimal(str(raw_value))
    else:
        text_value = _required_text(raw_value, "marker value")

    reference_min = (
        Decimal(str(marker["reference_min"]))
        if marker.get("reference_min") is not None
        else None
    )
    reference_max = (
        Decimal(str(marker["reference_max"]))
        if marker.get("reference_max") is not None
        else None
    )
    if (
        reference_min is not None
        and reference_max is not None
        and reference_min > reference_max
    ):
        raise MedicalLabImportError(
            f"Invalid reference range for marker '{marker['name']}'"
        )

    return MedicalLabResult(
        user_id=user_id,
        marker_name=_required_text(marker["name"], "marker name"),
        marker_code=_optional_text(marker.get("code")),
        value=numeric_value,
        value_text=text_value,
        unit=_required_text(marker["unit"], "marker unit"),
        reference_min=reference_min,
        reference_max=reference_max,
        reference_text=_optional_text(marker.get("reference_text")),
        status=marker.get("status", "unknown"),
        notes=_optional_text(marker.get("notes")),
    )


def import_medical_lab_file(
    source_file: UploadedFile,
    user_id: int,
) -> tuple[MedicalLabReport, bool]:
    if source_file.user_id != user_id:
        raise MedicalLabImportError("Medical lab file does not belong to this user")

    existing = _existing_report(source_file.id, user_id)
    if existing is not None:
        mark_import_status(
            source_file,
            user_id,
            status="duplicate",
            detected_type="medical_lab",
        )
        return existing, True

    try:
        if source_file.source_type not in {"uploaded", "manual_generated"}:
            raise MedicalLabImportError("Unsupported medical lab source file type")
        try:
            document = load_json_source(source_file, user_id)
        except ImporterError as error:
            raise MedicalLabImportError(str(error)) from error
        validate_json_document(document, "medical_lab")
        if document["user_id"] != user_id:
            raise MedicalLabImportError(
                "Medical lab document does not belong to this user"
            )
        if document["source_type"] != source_file.source_type:
            raise MedicalLabImportError(
                "Medical lab source type does not match its file"
            )

        source = _required_text(
            document.get("source", document["source_type"]),
            "medical lab source",
        )
        report = MedicalLabReport(
            user_id=user_id,
            date=date.fromisoformat(document["date"]),
            laboratory_name=_optional_text(document.get("laboratory_name")),
            doctor_name=_optional_text(document.get("doctor_name")),
            source=source,
            source_file_id=source_file.id,
            notes=_optional_text(document.get("notes")),
            raw_payload_json=document,
        )
        report.results = [
            _result_from_marker(marker, user_id=user_id)
            for marker in document["markers"]
        ]
        db.session.add(report)
        db.session.commit()
    except (JsonSchemaValidationError, MedicalLabImportError, ValueError) as error:
        db.session.rollback()
        mark_import_status(
            source_file,
            user_id,
            status="error",
            detected_type="medical_lab",
            error_message=str(error),
        )
        raise

    mark_import_status(
        source_file,
        user_id,
        status="imported",
        detected_type="medical_lab",
    )
    return report, False
