"""Read-only orchestration service for assisted imports.

This service coordinates the first safe phase of assisted imports:

payload
    -> SchemaDetector
    -> UniversalJsonImportAssistant
    -> StandardJsonGenerator

It does not write to the database.
It does not store files.
It does not import records.
It does not create ImportJob rows.

The output is a single preview payload that later can be connected to routes,
UI, ImportJob, stored generated files, and official importers.
"""

from __future__ import annotations

from typing import Any

from app.services.importers.schema_detector import SchemaDetector
from app.services.importers.standard_json_generator import StandardJsonGenerator
from app.services.importers.universal_json_import_assistant import (
    UniversalJsonImportAssistant,
)


class AssistedImportService:
    """Build a read-only assisted import preview."""

    def __init__(
        self,
        *,
        schema_detector: SchemaDetector | None = None,
        assistant: UniversalJsonImportAssistant | None = None,
        standard_json_generator: StandardJsonGenerator | None = None,
    ) -> None:
        self.schema_detector = schema_detector or SchemaDetector()
        self.assistant = assistant or UniversalJsonImportAssistant(
            schema_detector=self.schema_detector,
        )
        self.standard_json_generator = (
            standard_json_generator or StandardJsonGenerator()
        )

    def preview(
        self,
        payload: dict[str, Any],
        *,
        user_id: int,
        requested_type: str | None = None,
        target_type: str | None = None,
        source_type: str = "uploaded",
        default_timezone: str = "+00:00",
        candidate_index: int = 0,
        generate_standard_json: bool = True,
    ) -> dict[str, Any]:
        """Return a read-only preview for a JSON payload.

        Modes returned:

        - invalid
        - standard_ready
        - assistant_required_without_candidates
        - assistant_preview_ready
        - standard_json_generated
        - standard_json_generated_with_errors
        """

        if not isinstance(payload, dict):
            return {
                "mode": "invalid",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": target_type,
                "schema_detection": None,
                "assistant_result": None,
                "selected_candidate": None,
                "standard_generation": None,
                "summary": {
                    "candidate_count": 0,
                    "generated_count": 0,
                    "valid_count": 0,
                    "invalid_count": 0,
                    "warnings": ["The uploaded JSON must be an object."],
                    "actions_available": ["cancel"],
                },
            }

        schema_detection = self.schema_detector.detect(
            payload,
            requested_type=requested_type,
        )

        if schema_detection["mode"] == "standard":
            return {
                "mode": "standard_ready",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": target_type or schema_detection["detected_type"],
                "schema_detection": schema_detection,
                "assistant_result": None,
                "selected_candidate": None,
                "standard_generation": None,
                "summary": {
                    "candidate_count": 0,
                    "generated_count": 0,
                    "valid_count": 0,
                    "invalid_count": 0,
                    "warnings": [
                        "This file already matches an official internal schema."
                    ],
                    "actions_available": [
                        "import_with_standard_importer",
                        "cancel",
                    ],
                },
            }

        assistant_result = self.assistant.analyze(
            payload,
            requested_type=requested_type,
        )

        if assistant_result.get("mode") == "invalid":
            return {
                "mode": "invalid",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": target_type,
                "schema_detection": schema_detection,
                "assistant_result": assistant_result,
                "selected_candidate": None,
                "standard_generation": None,
                "summary": self._summary(
                    assistant_result=assistant_result,
                    standard_generation=None,
                ),
            }

        candidates = assistant_result.get("candidate_domains") or []
        if not candidates:
            return {
                "mode": "assistant_required_without_candidates",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": target_type,
                "schema_detection": schema_detection,
                "assistant_result": assistant_result,
                "selected_candidate": None,
                "standard_generation": None,
                "summary": self._summary(
                    assistant_result=assistant_result,
                    standard_generation=None,
                ),
            }

        selected_candidate = self._select_candidate(
            candidates,
            target_type=target_type,
            candidate_index=candidate_index,
        )

        if selected_candidate is None:
            return {
                "mode": "assistant_required_without_candidates",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": target_type,
                "schema_detection": schema_detection,
                "assistant_result": assistant_result,
                "selected_candidate": None,
                "standard_generation": None,
                "summary": self._summary(
                    assistant_result=assistant_result,
                    standard_generation=None,
                    extra_warnings=[
                        "No candidate matched the requested target or candidate index."
                    ],
                ),
            }

        if not generate_standard_json:
            return {
                "mode": "assistant_preview_ready",
                "read_only": True,
                "requested_type": requested_type,
                "target_type": selected_candidate.get("target_type"),
                "schema_detection": schema_detection,
                "assistant_result": assistant_result,
                "selected_candidate": selected_candidate,
                "standard_generation": None,
                "summary": self._summary(
                    assistant_result=assistant_result,
                    standard_generation=None,
                ),
            }

        standard_generation = self.standard_json_generator.generate(
            payload,
            selected_candidate,
            user_id=user_id,
            source_type=source_type,
            default_timezone=default_timezone,
        )

        mode = self._mode_from_generation(standard_generation)

        return {
            "mode": mode,
            "read_only": True,
            "requested_type": requested_type,
            "target_type": selected_candidate.get("target_type"),
            "schema_detection": schema_detection,
            "assistant_result": assistant_result,
            "selected_candidate": selected_candidate,
            "standard_generation": standard_generation,
            "summary": self._summary(
                assistant_result=assistant_result,
                standard_generation=standard_generation,
            ),
        }

    @staticmethod
    def _select_candidate(
        candidates: list[dict[str, Any]],
        *,
        target_type: str | None,
        candidate_index: int,
    ) -> dict[str, Any] | None:
        if target_type:
            for candidate in candidates:
                if candidate.get("target_type") == target_type:
                    return candidate
            return None

        if candidate_index < 0 or candidate_index >= len(candidates):
            return None

        return candidates[candidate_index]

    @staticmethod
    def _mode_from_generation(standard_generation: dict[str, Any]) -> str:
        if standard_generation.get("mode") == "unsupported_target":
            return "assistant_preview_ready"

        validation_items = standard_generation.get("validated_documents") or []
        if not validation_items:
            return "standard_json_generated_with_errors"

        if all(item.get("valid") is True for item in validation_items):
            return "standard_json_generated"

        return "standard_json_generated_with_errors"

    @staticmethod
    def _summary(
        *,
        assistant_result: dict[str, Any] | None,
        standard_generation: dict[str, Any] | None,
        extra_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        preview = {}

        if assistant_result:
            candidates = assistant_result.get("candidate_domains") or []
            preview = assistant_result.get("preview") or {}

        validation_items = []
        generated_documents = []

        if standard_generation:
            validation_items = standard_generation.get("validated_documents") or []
            generated_documents = standard_generation.get("generated_documents") or []

        valid_count = sum(1 for item in validation_items if item.get("valid") is True)
        invalid_count = sum(1 for item in validation_items if item.get("valid") is False)

        warnings: list[str] = []
        warnings.extend(preview.get("warnings") or [])

        if standard_generation:
            warnings.extend(standard_generation.get("warnings") or [])
            if standard_generation.get("mode") == "unsupported_target":
                warnings.append(
                    "The selected candidate is previewable, but standard JSON "
                    "generation is not implemented for this target yet."
                )

        if extra_warnings:
            warnings.extend(extra_warnings)

        actions_available = [
            "review_preview",
            "review_mapping",
            "cancel",
        ]

        if generated_documents:
            actions_available.insert(0, "review_generated_standard_json")

        if valid_count and invalid_count == 0:
            actions_available.insert(0, "import_with_standard_importer_later")

        return {
            "candidate_count": len(candidates),
            "generated_count": len(generated_documents),
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "warnings": warnings,
            "actions_available": actions_available,
        }