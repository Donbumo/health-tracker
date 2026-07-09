"""Read-only standard JSON generation for assisted imports.

This module converts a detected candidate mapping into official internal JSON
documents, then validates those documents against the existing schemas.

It does not write to the database.
It does not store files.
It does not import records.

Current supported preview targets:

- weigh_in_batch -> generated weigh_in documents
- food_products  -> generated food_product documents
- daily_energy   -> generated daily_energy documents
- completed_workout -> generated completed_workout documents
- medical_lab    -> generated medical_lab documents
"""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators import (
    completed_workout,
    daily_energy,
    food_product,
    medical_lab,
    weigh_in,
)
from app.services.importers.standard_generators import common
from app.services.validation import JsonSchemaValidationError, validate_json_document


SUPPORTED_TARGETS = {
    "weigh_in_batch",
    "food_products",
    "daily_energy",
    "completed_workout",
    "medical_lab",
}

WEIGH_IN_SCHEMA_NAME = weigh_in.SCHEMA_NAME
FOOD_PRODUCT_SCHEMA_NAME = food_product.SCHEMA_NAME
DAILY_ENERGY_SCHEMA_NAME = daily_energy.SCHEMA_NAME
COMPLETED_WORKOUT_SCHEMA_NAME = completed_workout.SCHEMA_NAME
MEDICAL_LAB_SCHEMA_NAME = medical_lab.SCHEMA_NAME


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

        source_path = str(candidate.get("path", "$"))
        if target_type == "medical_lab":
            medical_parent_path = self._medical_lab_parent_path(source_path)
            if medical_parent_path is not None:
                source_path = medical_parent_path

        records = self._records_at_path(payload, source_path)
        mapping = candidate.get("suggested_mapping") or {}
        if not isinstance(mapping, dict):
            raise StandardJsonGenerationError("candidate.suggested_mapping must be an object")

        generated_documents, warnings, schema_name = self._generate_for_target(
            target_type=target_type,
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
            default_timezone=default_timezone,
        )

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

    def _generate_for_target(
        self,
        *,
        target_type: str,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
        default_timezone: str,
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        if target_type == "weigh_in_batch":
            generated_documents, warnings = self._generate_weigh_ins(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
                default_timezone=default_timezone,
            )
            return generated_documents, warnings, WEIGH_IN_SCHEMA_NAME

        if target_type == "food_products":
            generated_documents, warnings = self._generate_food_products(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=source_type,
            )
            return generated_documents, warnings, FOOD_PRODUCT_SCHEMA_NAME

        if target_type == "daily_energy":
            generated_documents, warnings = self._generate_daily_energy(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
            )
            return generated_documents, warnings, DAILY_ENERGY_SCHEMA_NAME

        if target_type == "completed_workout":
            generated_documents, warnings = self._generate_completed_workouts(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
                default_timezone=default_timezone,
            )
            return generated_documents, warnings, COMPLETED_WORKOUT_SCHEMA_NAME

        generated_documents, warnings = self._generate_medical_labs(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=self._medical_lab_source_type(source_type),
        )
        return generated_documents, warnings, MEDICAL_LAB_SCHEMA_NAME

    def _generate_weigh_ins(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
        default_timezone: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return weigh_in.generate(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
            default_timezone=default_timezone,
        )

    def _generate_food_products(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return food_product.generate(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
        )

    def _generate_daily_energy(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return daily_energy.generate(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
        )

    def _generate_completed_workouts(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
        default_timezone: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return completed_workout.generate(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
            default_timezone=default_timezone,
        )

    def _generate_medical_labs(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return medical_lab.generate(
            records=records,
            mapping=mapping,
            user_id=user_id,
            source_type=source_type,
        )

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
        return common.records_at_path(payload, path)

    def _value_at_path(self, payload: dict[str, Any], path: str) -> Any:
        return common.value_at_path(payload, path)

    @staticmethod
    def _path_tokens(path: str) -> list[str | int]:
        return common.path_tokens(path)

    @staticmethod
    def _coerce_number(value: Any) -> int | float | None:
        return common.coerce_number(value)

    def _coerce_datetime(
        self,
        date_value: Any,
        time_value: Any = None,
        *,
        default_timezone: str,
    ) -> Any:
        return common.coerce_datetime(
            date_value,
            time_value,
            default_timezone=default_timezone,
        )

    @staticmethod
    def _coerce_time_text(value: Any) -> str | None:
        return common.coerce_time_text(value)

    @staticmethod
    def _has_timezone(value: str) -> bool:
        return common.has_timezone(value)

    @staticmethod
    def _medical_lab_parent_path(path: str) -> str | None:
        return medical_lab.parent_path(path)

    @staticmethod
    def _medical_lab_source_type(source_type: str) -> str:
        return medical_lab.normalize_source_type(source_type)

    @staticmethod
    def _weigh_in_source_type(source_type: str) -> str:
        return weigh_in.normalize_source_type(source_type)

    @staticmethod
    def _drop_none(document: dict[str, Any]) -> dict[str, Any]:
        return common.drop_none(document)
