"""Standard JSON generation for assisted food product candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import coerce_number


SCHEMA_NAME = "food_product"

FIELDS = {
    "name",
    "brand",
    "serving_size_g",
    "serving_label",
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
    "source",
    "notes",
}

NUMERIC_FIELDS = {
    "serving_size_g",
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
}


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, record in enumerate(records):
        document: dict[str, Any] = {
            "schema_version": "1.0",
            "type": "food_product",
            "user_id": user_id,
            "source_type": source_type,
            "source": "assisted_import",
        }

        for source_field, canonical_field in mapping.items():
            if source_field not in record:
                continue

            value = record[source_field]

            if canonical_field not in FIELDS:
                warnings.append(
                    f"record {index}: unsupported food_product field ignored: {canonical_field}"
                )
                continue

            if canonical_field in NUMERIC_FIELDS:
                document[canonical_field] = coerce_number(value)
            else:
                document[canonical_field] = value

        if "name" not in document:
            document["name"] = None

        documents.append(document)

    return documents, warnings
