import csv
from datetime import timezone
from io import StringIO
from typing import Iterable

from app.models import WeighIn
from app.services.exporters.base import BaseExporter, ExportArtifact, serialize_json
from app.services.validation import validate_json_document


def _number(value):
    return float(value) if value is not None else None


def _source_type(record: WeighIn) -> str:
    if record.source_file is not None and record.source_file.source_type in {
        "manual_generated",
        "uploaded",
        "device_sync",
    }:
        return record.source_file.source_type
    return "uploaded"


def _recorded_at(record: WeighIn) -> str:
    value = record.recorded_at
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")


def build_weigh_in_document(record: WeighIn, user_id: int) -> dict:
    if record.user_id != user_id:
        raise ValueError("Weigh-in does not belong to this user")
    data = {
        "recorded_at": _recorded_at(record),
        "weight_kg": _number(record.weight_kg),
        "source": record.source,
    }
    for field, value in {
        "body_fat_percent": record.body_fat_percentage,
        "muscle_mass_kg": record.muscle_mass_kg,
        "water_percent": record.water_percentage,
        "visceral_fat": record.visceral_fat,
        "bmr_kcal": record.bmr_kcal,
        "bmi": record.bmi,
    }.items():
        if value is not None:
            data[field] = _number(value)
    if record.notes:
        data["notes"] = record.notes
    return {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": user_id,
        "source_type": _source_type(record),
        "data": data,
    }


class WeighInJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: WeighIn, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_weigh_in_document(resource, user_id)
        validate_json_document(document, "weigh_in")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )


class WeighInHistoryCsvExporter(BaseExporter):
    format_name = "csv"

    def export(
        self,
        resource: Iterable[WeighIn],
        user_id: int,
    ) -> ExportArtifact:
        records = list(resource)
        for record in records:
            self.ensure_owner(record, user_id)

        output = StringIO(newline="")
        fieldnames = (
            "recorded_at",
            "weight_kg",
            "body_fat_percentage",
            "muscle_mass_kg",
            "water_percentage",
            "visceral_fat",
            "bmr_kcal",
            "bmi",
            "source",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    field: _recorded_at(record)
                    if field == "recorded_at"
                    else getattr(record, field)
                    for field in fieldnames
                }
            )
        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
            warning="CSV conserva el resumen corporal; usa JSON para un pesaje completo.",
        )
