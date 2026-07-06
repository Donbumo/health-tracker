"""Strict JSON schema detection for uploaded JSON documents.

The detector only answers one question:

    Does this payload already match one of our official internal schemas?

It intentionally does not guess non-standard formats. If no official schema
matches, callers should route the payload to the assisted import preview flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.validation import JsonSchemaValidationError, validate_json_document


DEFAULT_SCHEMA_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("weigh_in", "weigh_in"),
    ("daily_nutrition", "daily_nutrition"),
    ("daily_energy", "daily_energy"),
    ("food_product", "food_product"),
    ("recipe_bundle", "recipe_bundle"),
    ("recipe", "recipe"),
    ("medical_lab", "medical_lab"),
    ("training_plan", "training_plan"),
    ("completed_workout", "completed_workout"),
    ("user_data_export", "user_data_export"),
)


@dataclass(frozen=True)
class SchemaDetection:
    mode: str
    detected_type: str
    confidence: float
    schema_name: str | None = None
    requested_type: str | None = None
    errors: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "detected_type": self.detected_type,
            "confidence": self.confidence,
            "schema_name": self.schema_name,
            "requested_type": self.requested_type,
            "errors": self.errors or [],
        }


class SchemaDetector:
    """Detect whether a JSON payload matches an official schema.

    This class is deliberately strict. It should not attempt heuristic mapping.
    Heuristics belong in UniversalJsonImportAssistant.
    """

    def __init__(
        self,
        schema_candidates: tuple[tuple[str, str], ...] = DEFAULT_SCHEMA_CANDIDATES,
    ) -> None:
        self.schema_candidates = schema_candidates

    def detect(
        self,
        payload: dict[str, Any],
        requested_type: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return SchemaDetection(
                mode="assistant_required",
                detected_type=requested_type or "unknown",
                confidence=0.0,
                requested_type=requested_type,
                errors=["Payload must be a JSON object."],
            ).as_dict()

        candidates = self._ordered_candidates(requested_type)
        validation_errors: list[str] = []

        for detected_type, schema_name in candidates:
            try:
                validate_json_document(payload, schema_name)
            except JsonSchemaValidationError as error:
                validation_errors.append(
                    f"{schema_name}: {len(error.errors)} validation error(s)"
                )
                continue

            return SchemaDetection(
                mode="standard",
                detected_type=detected_type,
                confidence=1.0,
                schema_name=schema_name,
                requested_type=requested_type,
                errors=[],
            ).as_dict()

        fallback_detected_type = (
            requested_type
            or self._declared_type(payload)
            or "unknown"
        )

        return SchemaDetection(
            mode="assistant_required",
            detected_type=fallback_detected_type,
            confidence=0.0,
            schema_name=None,
            requested_type=requested_type,
            errors=validation_errors[:10],
        ).as_dict()

    def _ordered_candidates(
        self,
        requested_type: str | None,
    ) -> tuple[tuple[str, str], ...]:
        if not requested_type:
            return self.schema_candidates

        requested = []
        remaining = []

        for detected_type, schema_name in self.schema_candidates:
            if detected_type == requested_type or schema_name == requested_type:
                requested.append((detected_type, schema_name))
            else:
                remaining.append((detected_type, schema_name))

        return tuple(requested + remaining)

    @staticmethod
    def _declared_type(payload: dict[str, Any]) -> str | None:
        declared = payload.get("record_type") or payload.get("type")
        if isinstance(declared, str) and declared.strip():
            return declared.strip()
        return None