"""Standard JSON generation for assisted daily energy candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_number,
    drop_none,
)
from app.services.importers.standard_generators.weigh_in import (
    normalize_source_type,
)


SCHEMA_NAME = "daily_energy"

DATA_FIELDS = {
    "date",
    "total_expenditure_kcal",
    "resting_expenditure_kcal",
    "active_expenditure_kcal",
    "steps",
    "distance_meters",
    "source",
    "notes",
}

ALIAS_TO_SCHEMA = {
    "total_calories": "total_expenditure_kcal",
    "resting_calories": "resting_expenditure_kcal",
    "active_calories": "active_expenditure_kcal",
    "distance_km": None,  # needs unit conversion, handled separately
    "steps": "steps",
    "date": "date",
    "source": "source",
    "notes": "notes",
    # passthrough: schema field names map to themselves
    "total_expenditure_kcal": "total_expenditure_kcal",
    "resting_expenditure_kcal": "resting_expenditure_kcal",
    "active_expenditure_kcal": "active_expenditure_kcal",
    "distance_meters": "distance_meters",
}

NUMERIC_FIELDS = {
    "total_expenditure_kcal",
    "resting_expenditure_kcal",
    "active_expenditure_kcal",
    "distance_meters",
}


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate daily_energy documents from an assisted candidate mapping.

    The assistant canonical values (e.g. total_calories, active_calories)
    are translated to schema field names (e.g. total_expenditure_kcal,
    active_expenditure_kcal). distance_km is converted to distance_meters.
    """

    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, record in enumerate(records):
        data: dict[str, Any] = {
            "source": "assisted_import",
        }

        for source_field, canonical in mapping.items():
            if source_field not in record:
                continue

            value = record[source_field]

            if canonical == "distance_km":
                num = coerce_number(value)
                if num is not None:
                    data["distance_meters"] = round(num * 1000, 3)
                continue

            schema_field = ALIAS_TO_SCHEMA.get(canonical)
            if schema_field is None:
                warnings.append(
                    f"record {index}: unsupported daily_energy field "
                    f"ignored: {canonical} (from source: {source_field})"
                )
                continue

            if schema_field not in DATA_FIELDS:
                warnings.append(
                    f"record {index}: unknown daily_energy schema field ignored: {schema_field}"
                )
                continue

            if schema_field == "steps":
                num = coerce_number(value)
                data["steps"] = int(num) if num is not None else None
            elif schema_field in NUMERIC_FIELDS:
                data[schema_field] = coerce_number(value)
            else:
                data[schema_field] = value

        documents.append(
            {
                "schema_version": "1.0",
                "record_type": "daily_energy",
                "user_id": user_id,
                "source_type": source_type,
                "data": drop_none(data),
            }
        )

    return documents, warnings
