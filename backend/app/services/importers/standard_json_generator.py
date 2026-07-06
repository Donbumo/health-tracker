"""Read-only standard JSON generation for assisted imports.

This module converts a detected candidate mapping into official internal JSON
documents, then validates those documents against the existing schemas.

It does not write to the database.
It does not store files.
It does not import records.

Current supported preview targets:

- weigh_in_batch -> generated weigh_in documents
- food_products  -> generated food_product documents
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.services.validation import JsonSchemaValidationError, validate_json_document


SUPPORTED_TARGETS = {
    "weigh_in_batch",
    "food_products",
}

WEIGH_IN_SCHEMA_NAME = "weigh_in"
FOOD_PRODUCT_SCHEMA_NAME = "food_product"

WEIGH_IN_DATA_FIELDS = {
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

WEIGH_IN_NUMERIC_FIELDS = {
    "weight_kg",
    "body_fat_percent",
    "muscle_mass_kg",
    "water_percent",
    "visceral_fat",
    "bmr_kcal",
    "bmi",
}

FOOD_PRODUCT_FIELDS = {
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

FOOD_PRODUCT_NUMERIC_FIELDS = {
    "serving_size_g",
    "calories_per_100g",
    "protein_g_per_100g",
    "fat_g_per_100g",
    "carbs_g_per_100g",
    "net_carbs_g_per_100g",
    "fiber_g_per_100g",
    "sodium_mg_per_100g",
}


class StandardJsonGenerationError(ValueError):
    pass


class StandardJsonGenerator:
    """Generate official JSON documents from an assisted preview candidate."""

    def generate(
        self,
        payload: dict[str, Any],
        candidate: dict[str, Any],
        *,
        user_id: int,
        source_type: str = "uploaded",
        default_timezone: str = "+00:00",
    ) -> dict[str, Any]:
        target_type = candidate.get("target_type")
        if target_type not in SUPPORTED_TARGETS:
            return {
                "mode": "unsupported_target",
                "target_type": target_type,
                "source_path": candidate.get("path"),
                "records_detected": 0,
                "generated_documents": [],
                "validated_documents": [],
                "warnings": [f"Unsupported target_type for standard generation: {target_type}"],
            }

        records = self._records_at_path(payload, str(candidate.get("path", "$")))
        mapping = candidate.get("suggested_mapping") or {}
        if not isinstance(mapping, dict):
            raise StandardJsonGenerationError("candidate.suggested_mapping must be an object")

        if target_type == "weigh_in_batch":
            generated_documents, warnings = self._generate_weigh_ins(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
                default_timezone=default_timezone,
            )
            schema_name = WEIGH_IN_SCHEMA_NAME
        else:
            generated_documents, warnings = self._generate_food_products(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=source_type,
            )
            schema_name = FOOD_PRODUCT_SCHEMA_NAME

        validated_documents = [
            self._validate_document(index, document, schema_name)
            for index, document in enumerate(generated_documents)
        ]

        return {
            "mode": "standard_json_generated",
            "target_type": target_type,
            "source_path": candidate.get("path"),
            "schema_name": schema_name,
            "records_detected": len(records),
            "generated_documents": generated_documents,
            "validated_documents": validated_documents,
            "warnings": warnings,
        }

    def _generate_weigh_ins(
        self,
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

                if canonical_field not in WEIGH_IN_DATA_FIELDS:
                    warnings.append(
                        f"record {index}: unsupported weigh_in field ignored: {canonical_field}"
                    )
                    continue

                if canonical_field in WEIGH_IN_NUMERIC_FIELDS:
                    data[canonical_field] = self._coerce_number(value)
                else:
                    data[canonical_field] = value

            if pending_date_value is not None:
                data["recorded_at"] = self._coerce_datetime(
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
                    "data": self._drop_none(data),
                }
            )

        return documents, warnings

    def _generate_food_products(
        self,
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

                if canonical_field not in FOOD_PRODUCT_FIELDS:
                    warnings.append(
                        f"record {index}: unsupported food_product field ignored: {canonical_field}"
                    )
                    continue

                if canonical_field in FOOD_PRODUCT_NUMERIC_FIELDS:
                    document[canonical_field] = self._coerce_number(value)
                else:
                    document[canonical_field] = value

            if "name" not in document:
                document["name"] = None

            documents.append(document)

        return documents, warnings

    @staticmethod
    def _validate_document(
        index: int,
        document: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        try:
            validate_json_document(document, schema_name)
        except JsonSchemaValidationError as error:
            return {
                "index": index,
                "valid": False,
                "schema_name": schema_name,
                "errors": error.errors,
            }

        return {
            "index": index,
            "valid": True,
            "schema_name": schema_name,
            "errors": [],
        }

    def _records_at_path(self, payload: dict[str, Any], path: str) -> list[dict[str, Any]]:
        node = self._value_at_path(payload, path)

        if isinstance(node, list):
            return [
                deepcopy(item)
                for item in node
                if isinstance(item, dict)
            ]

        if isinstance(node, dict):
            return [deepcopy(node)]

        return []

    def _value_at_path(self, payload: dict[str, Any], path: str) -> Any:
        if path in {"", "$"}:
            return payload

        current: Any = payload
        for token in self._path_tokens(path):
            if isinstance(token, str):
                if not isinstance(current, dict):
                    return None
                current = current.get(token)
            else:
                if not isinstance(current, list):
                    return None
                if token < 0 or token >= len(current):
                    return None
                current = current[token]

        return current

    @staticmethod
    def _path_tokens(path: str) -> list[str | int]:
        tokens: list[str | int] = []

        for part in path.split("."):
            if not part:
                continue

            match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
            if not match:
                tokens.append(part)
                continue

            key, index = match.groups()
            tokens.append(key)
            if index is not None:
                tokens.append(int(index))

        return tokens

    @staticmethod
    def _coerce_number(value: Any) -> int | float | None:
        if value is None:
            return None

        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return value

        try:
            decimal_value = Decimal(str(value).strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            return None

        if decimal_value == decimal_value.to_integral_value():
            return int(decimal_value)

        return float(decimal_value)

    def _coerce_datetime(
        self,
        date_value: Any,
        time_value: Any = None,
        *,
        default_timezone: str,
    ) -> Any:
        if date_value is None:
            return None

        text = str(date_value).strip()
        if not text:
            return None

        if "T" in text:
            if self._has_timezone(text):
                return text
            return f"{text}{default_timezone}"

        time_text = self._coerce_time_text(time_value) or "00:00:00"
        return f"{text}T{time_text}{default_timezone}"

    @staticmethod
    def _coerce_time_text(value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, time):
            return value.strftime("%H:%M:%S")

        text = str(value).strip()
        if not text:
            return None

        if re.fullmatch(r"\d{2}:\d{2}", text):
            return f"{text}:00"

        if re.fullmatch(r"\d{2}:\d{2}:\d{2}", text):
            return text

        return None

    @staticmethod
    def _has_timezone(value: str) -> bool:
        if value.endswith("Z"):
            return True
        return bool(re.search(r"[+-]\d{2}:\d{2}$", value))

    @staticmethod
    def _weigh_in_source_type(source_type: str) -> str:
        if source_type in {"manual_generated", "uploaded", "device_sync"}:
            return source_type
        return "uploaded"

    @staticmethod
    def _drop_none(document: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in document.items()
            if value is not None
        }