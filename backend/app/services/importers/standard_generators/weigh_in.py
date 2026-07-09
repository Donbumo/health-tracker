"""Standard JSON generation for assisted weigh-in candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_datetime,
    coerce_number,
    drop_none,
)


SCHEMA_NAME = "weigh_in"

DATA_FIELDS = {
    "recorded_at",
    "weight_kg",
    "body_fat_percent",
    "muscle_mass_kg",
    "water_percent",
    "visceral_fat",
    "bmr_kcal",
    "bmi",
    "source",
    "notes",
}

NUMERIC_FIELDS = {
    "weight_kg",
    "body_fat_percent",
    "muscle_mass_kg",
    "water_percent",
    "visceral_fat",
    "bmr_kcal",
    "bmi",
}


def normalize_source_type(source_type: str) -> str:
    if source_type in {"manual_generated", "uploaded", "device_sync"}:
        return source_type
    return "uploaded"


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
    default_timezone: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, record in enumerate(records):
        data: dict[str, Any] = {
            "source": "assisted_import",
        }
        pending_date_value: Any = None
        pending_time: Any = None

        for source_field, canonical_field in mapping.items():
            if source_field not in record:
                continue

            value = record[source_field]

            if canonical_field == "recorded_time":
                pending_time = value
                continue

            if canonical_field == "recorded_at":
                pending_date_value = value
                continue

            if canonical_field not in DATA_FIELDS:
                warnings.append(
                    f"record {index}: unsupported weigh_in field ignored: {canonical_field}"
                )
                continue

            if canonical_field in NUMERIC_FIELDS:
                data[canonical_field] = coerce_number(value)
            else:
                data[canonical_field] = value

        if pending_date_value is not None:
            data["recorded_at"] = coerce_datetime(
                pending_date_value,
                pending_time,
                default_timezone=default_timezone,
            )

        documents.append(
            {
                "schema_version": "1.0",
                "record_type": "weigh_in",
                "user_id": user_id,
                "source_type": source_type,
                "data": drop_none(data),
            }
        )

    return documents, warnings
