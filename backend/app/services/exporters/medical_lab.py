import csv
from io import StringIO
from typing import Iterable

from app.models import MedicalLabReport
from app.services.exporters.base import BaseExporter, ExportArtifact, ExportError, serialize_json
from app.services.validation import validate_json_document


def _number(value):
    return float(value) if value is not None else None


def _source_type(report: MedicalLabReport) -> str:
    if report.source_file is not None and report.source_file.source_type in {
        "manual_generated",
        "uploaded",
    }:
        return report.source_file.source_type
    return "manual_generated"


def build_medical_lab_document(report: MedicalLabReport, user_id: int) -> dict:
    if report.user_id != user_id:
        raise ExportError("Medical lab report does not belong to this user")
    document = {
        "schema_version": "1.0",
        "type": "medical_lab",
        "user_id": user_id,
        "source_type": _source_type(report),
        "date": report.date.isoformat(),
        "source": report.source,
        "markers": [],
    }
    for field in ("laboratory_name", "doctor_name", "notes"):
        value = getattr(report, field)
        if value:
            document[field] = value

    for result in report.results:
        if result.user_id != user_id:
            raise ExportError("Medical lab result does not belong to this user")
        marker = {
            "name": result.marker_name,
            "value": (
                _number(result.value)
                if result.value is not None
                else result.value_text
            ),
            "unit": result.unit,
            "status": result.status,
        }
        for model_field, document_field in (
            ("marker_code", "code"),
            ("reference_text", "reference_text"),
            ("notes", "notes"),
        ):
            value = getattr(result, model_field)
            if value:
                marker[document_field] = value
        if result.reference_min is not None:
            marker["reference_min"] = _number(result.reference_min)
        if result.reference_max is not None:
            marker["reference_max"] = _number(result.reference_max)
        document["markers"].append(marker)
    return document


class MedicalLabJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: MedicalLabReport, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_medical_lab_document(resource, user_id)
        validate_json_document(document, "medical_lab")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )


class MedicalLabCsvExporter(BaseExporter):
    format_name = "csv"
    fieldnames = (
        "report_date",
        "laboratory_name",
        "doctor_name",
        "source",
        "marker_name",
        "marker_code",
        "value",
        "value_text",
        "unit",
        "reference_min",
        "reference_max",
        "reference_text",
        "status",
        "notes",
    )

    def export(self, resource: MedicalLabReport, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        output = StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=self.fieldnames)
        writer.writeheader()
        for result in resource.results:
            if result.user_id != user_id:
                raise ExportError("Medical lab result does not belong to this user")
            writer.writerow(
                {
                    "report_date": resource.date.isoformat(),
                    "laboratory_name": resource.laboratory_name,
                    "doctor_name": resource.doctor_name,
                    "source": resource.source,
                    "marker_name": result.marker_name,
                    "marker_code": result.marker_code,
                    "value": result.value,
                    "value_text": result.value_text,
                    "unit": result.unit,
                    "reference_min": result.reference_min,
                    "reference_max": result.reference_max,
                    "reference_text": result.reference_text,
                    "status": result.status,
                    "notes": result.notes,
                }
            )
        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
            warning="CSV aplana el reporte; usa JSON para conservar la estructura.",
        )


class MedicalMarkerHistoryCsvExporter(BaseExporter):
    format_name = "csv"

    def export(self, resource: Iterable[dict], user_id: int) -> ExportArtifact:
        entries = list(resource)
        output = StringIO(newline="")
        fieldnames = (
            "date",
            "marker_name",
            "value",
            "value_text",
            "unit",
            "status",
            "laboratory_name",
            "change_previous",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            result = entry["result"]
            report = entry["report"]
            if result.user_id != user_id or report.user_id != user_id:
                raise ExportError("Medical marker history does not belong to this user")
            writer.writerow(
                {
                    "date": report.date.isoformat(),
                    "marker_name": result.marker_name,
                    "value": result.value,
                    "value_text": result.value_text,
                    "unit": result.unit,
                    "status": result.status,
                    "laboratory_name": report.laboratory_name,
                    "change_previous": entry["change_previous"],
                }
            )
        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
        )
