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

from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.services.validation import JsonSchemaValidationError, validate_json_document


SUPPORTED_TARGETS = {
    "weigh_in_batch",
    "food_products",
    "daily_energy",
    "completed_workout",
    "medical_lab",
}

WEIGH_IN_SCHEMA_NAME = "weigh_in"
FOOD_PRODUCT_SCHEMA_NAME = "food_product"
DAILY_ENERGY_SCHEMA_NAME = "daily_energy"
COMPLETED_WORKOUT_SCHEMA_NAME = "completed_workout"
MEDICAL_LAB_SCHEMA_NAME = "medical_lab"


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

# Canonical schema fields for daily_energy.schema.json
DAILY_ENERGY_DATA_FIELDS = {
    "date",
    "total_expenditure_kcal",
    "resting_expenditure_kcal",
    "active_expenditure_kcal",
    "steps",
    "distance_meters",
    "source",
    "notes",
}

# Mapping from DAILY_ENERGY_ALIASES canonical values -> schema field names.
# The assistant uses internal aliases like total_calories/active_calories;
# the schema uses total_expenditure_kcal/active_expenditure_kcal.
_ENERGY_ALIAS_TO_SCHEMA = {
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

DAILY_ENERGY_NUMERIC_FIELDS = {
    "total_expenditure_kcal",
    "resting_expenditure_kcal",
    "active_expenditure_kcal",
    "distance_meters",
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

        source_path = str(candidate.get("path", "$"))
        if target_type == "medical_lab":
            medical_parent_path = self._medical_lab_parent_path(source_path)
            if medical_parent_path is not None:
                source_path = medical_parent_path

        records = self._records_at_path(payload, source_path)
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
        elif target_type == "food_products":
            generated_documents, warnings = self._generate_food_products(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=source_type,
            )
            schema_name = FOOD_PRODUCT_SCHEMA_NAME
        elif target_type == "daily_energy":
            generated_documents, warnings = self._generate_daily_energy(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
            )
            schema_name = DAILY_ENERGY_SCHEMA_NAME
        elif target_type == "completed_workout":
            generated_documents, warnings = self._generate_completed_workouts(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._weigh_in_source_type(source_type),
                default_timezone=default_timezone,
            )
            schema_name = COMPLETED_WORKOUT_SCHEMA_NAME
        else:
            generated_documents, warnings = self._generate_medical_labs(
                records=records,
                mapping=mapping,
                user_id=user_id,
                source_type=self._medical_lab_source_type(source_type),
            )
            schema_name = MEDICAL_LAB_SCHEMA_NAME

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

    def _generate_daily_energy(
        self,
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

                # Handle distance_km -> distance_meters conversion
                if canonical == "distance_km":
                    num = self._coerce_number(value)
                    if num is not None:
                        data["distance_meters"] = round(num * 1000, 3)
                    continue

                schema_field = _ENERGY_ALIAS_TO_SCHEMA.get(canonical)
                if schema_field is None:
                    warnings.append(
                        f"record {index}: unsupported daily_energy field "
                        f"ignored: {canonical} (from source: {source_field})"
                    )
                    continue

                if schema_field not in DAILY_ENERGY_DATA_FIELDS:
                    warnings.append(
                        f"record {index}: unknown daily_energy schema field ignored: {schema_field}"
                    )
                    continue

                if schema_field == "steps":
                    num = self._coerce_number(value)
                    data["steps"] = int(num) if num is not None else None
                elif schema_field in DAILY_ENERGY_NUMERIC_FIELDS:
                    data[schema_field] = self._coerce_number(value)
                else:
                    data[schema_field] = value

            documents.append(
                {
                    "schema_version": "1.0",
                    "record_type": "daily_energy",
                    "user_id": user_id,
                    "source_type": source_type,
                    "data": self._drop_none(data),
                }
            )

        return documents, warnings

    def _generate_completed_workouts(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
        default_timezone: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Generate completed_workout documents from an assisted candidate mapping.

        This method must not invent required plan, exercise, or set values.
        If required fields are missing, the generated document remains invalid
        and validation reports the missing fields.
        """
        from app.services.importers.universal_json_import_assistant import (
            COMPLETED_WORKOUT_ALIASES,
            _normalize_key,
        )

        local_aliases = {
            "training_plan_id": "training_plan_id",
            "training_plan_version_id": "training_plan_version_id",
            "planned_week_number": "planned_week_number",
            "planned_day_number": "planned_day_number",
            "fecha": "performed_at",
            "performed_at": "performed_at",
            "hora": "performed_time",
            "time": "performed_time",
            "performed_time": "performed_time",
            "rutina": "session_name",
            "sesion": "session_name",
            "session": "session_name",
            "session_name": "session_name",
            "duracion": "duration_seconds",
            "duration_seconds": "duration_seconds",
            "frecuencia_cardiaca": "average_heart_rate_bpm",
            "average_heart_rate_bpm": "average_heart_rate_bpm",
            "calorias": "calories_burned",
            "calories_burned": "calories_burned",
            "notas": "notes",
            "notes": "notes",
            "ejercicios": "exercises",
            "exercises": "exercises",
            "nombre": "name",
            "name": "name",
            "ejercicio": "name",
            "exercise_order": "exercise_order",
            "planned_exercise_order": "planned_exercise_order",
            "sets": "sets",
            "series": "sets",
            "set_number": "set_number",
            "planned_set_number": "planned_set_number",
            "peso": "weight_kg",
            "weight": "weight_kg",
            "weight_kg": "weight_kg",
            "reps": "reps",
            "rir": "rir",
            "rpe": "rpe",
            "descanso": "rest_seconds",
            "rest_seconds": "rest_seconds",
        }

        def _get_canonical(key: str) -> str | None:
            if key in mapping:
                return mapping[key]
            normalized = _normalize_key(key)
            if normalized in local_aliases:
                return local_aliases[normalized]
            return COMPLETED_WORKOUT_ALIASES.get(normalized)

        def _int_or_none(value: Any) -> int | None:
            number = self._coerce_number(value)
            if number is None:
                return None
            return int(number)

        def _float_or_none(value: Any) -> float | None:
            number = self._coerce_number(value)
            if number is None:
                return None
            return float(number)

        documents: list[dict[str, Any]] = []
        warnings: list[str] = []

        for index, record in enumerate(records):
            data: dict[str, Any] = {}
            pending_date_value: Any = None
            pending_time: Any = None
            exercises_source: Any = None

            for source_field, value in record.items():
                canonical = _get_canonical(source_field)
                if not canonical:
                    continue

                if canonical == "training_plan_id":
                    data["training_plan_id"] = _int_or_none(value)
                elif canonical == "training_plan_version_id":
                    data["training_plan_version_id"] = _int_or_none(value)
                elif canonical == "planned_week_number":
                    data["planned_week_number"] = _int_or_none(value)
                elif canonical == "planned_day_number":
                    data["planned_day_number"] = _int_or_none(value)
                elif canonical == "performed_at":
                    pending_date_value = value
                elif canonical == "performed_time":
                    pending_time = value
                elif canonical == "session_name":
                    data["notes"] = f"Session: {value}"
                elif canonical == "duration_seconds":
                    data["duration_seconds"] = _int_or_none(value)
                elif canonical == "average_heart_rate_bpm":
                    data["average_heart_rate_bpm"] = _int_or_none(value)
                elif canonical == "calories_burned":
                    data["calories_burned"] = _float_or_none(value)
                elif canonical == "notes":
                    data["notes"] = str(value)
                elif canonical == "exercises":
                    exercises_source = value

            if pending_date_value is not None:
                data["performed_at"] = self._coerce_datetime(
                    pending_date_value,
                    pending_time,
                    default_timezone=default_timezone,
                )

            exercises: list[dict[str, Any]] = []
            if isinstance(exercises_source, list):
                for ex_idx, ex_item in enumerate(exercises_source):
                    if not isinstance(ex_item, dict):
                        continue

                    ex_data: dict[str, Any] = {
                        "exercise_order": ex_idx + 1,
                        "planned_exercise_order": ex_idx + 1,
                    }
                    sets_source: Any = None

                    for source_field, value in ex_item.items():
                        canonical = _get_canonical(source_field)
                        if not canonical:
                            continue

                        if canonical == "exercise_order":
                            ex_data["exercise_order"] = _int_or_none(value)
                        elif canonical == "planned_exercise_order":
                            ex_data["planned_exercise_order"] = _int_or_none(value)
                        elif canonical == "name":
                            ex_data["name"] = str(value)
                        elif canonical == "notes":
                            ex_data["notes"] = str(value)
                        elif canonical == "sets":
                            sets_source = value

                    sets: list[dict[str, Any]] = []
                    if isinstance(sets_source, list):
                        for set_idx, set_item in enumerate(sets_source):
                            if not isinstance(set_item, dict):
                                continue

                            set_data: dict[str, Any] = {
                                "set_number": set_idx + 1,
                                "planned_set_number": set_idx + 1,
                            }

                            for source_field, value in set_item.items():
                                canonical = _get_canonical(source_field)
                                if not canonical:
                                    continue

                                if canonical == "set_number":
                                    set_data["set_number"] = _int_or_none(value)
                                elif canonical == "planned_set_number":
                                    set_data["planned_set_number"] = _int_or_none(value)
                                elif canonical == "weight_kg":
                                    set_data["weight_kg"] = _float_or_none(value)
                                elif canonical == "reps":
                                    set_data["reps"] = _int_or_none(value)
                                elif canonical == "rir":
                                    set_data["rir"] = _float_or_none(value)
                                elif canonical == "rpe":
                                    set_data["rpe"] = _float_or_none(value)
                                elif canonical == "rest_seconds":
                                    set_data["rest_seconds"] = _int_or_none(value)
                                elif canonical == "notes":
                                    set_data["notes"] = str(value)

                            sets.append(self._drop_none(set_data))

                    ex_data["sets"] = sets
                    exercises.append(self._drop_none(ex_data))

            data["exercises"] = exercises

            documents.append(
                {
                    "schema_version": "1.0",
                    "record_type": "completed_workout",
                    "user_id": user_id,
                    "source_type": source_type,
                    "data": self._drop_none(data),
                }
            )

        return documents, warnings

    def _generate_medical_labs(
        self,
        *,
        records: list[dict[str, Any]],
        mapping: dict[str, str],
        user_id: int,
        source_type: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Generate medical_lab documents from an assisted candidate mapping.

        This method must not invent required lab or marker values.
        If required fields are missing, validation reports the missing fields.
        """
        from app.services.importers.universal_json_import_assistant import (
            MEDICAL_LAB_ALIASES,
            _normalize_key,
        )

        local_aliases = {
            "laboratorio": "lab_name",
            "lab_name": "lab_name",
            "laboratory_name": "lab_name",
            "fecha": "lab_date",
            "lab_date": "lab_date",
            "date": "lab_date",
            "marcadores": "markers",
            "analitos": "markers",
            "markers": "markers",
            "marker": "name",
            "marcador": "name",
            "nombre": "name",
            "name": "name",
            "valor": "value",
            "value": "value",
            "unidad": "unit",
            "unit": "unit",
            "rango_referencia": "reference_range",
            "reference_range": "reference_range",
            "reference_text": "reference_range",
            "estado": "status",
            "status": "status",
            "notas": "notes",
            "notes": "notes",
            "codigo": "code",
            "code": "code",
            "glucosa": "glucose",
            "glucose": "glucose",
            "insulina": "insulin",
            "insulin": "insulin",
            "hba1c": "hba1c",
            "colesterol": "total_cholesterol",
            "colesterol_total": "total_cholesterol",
            "total_cholesterol": "total_cholesterol",
            "hdl": "hdl",
            "ldl": "ldl",
            "trigliceridos": "triglycerides",
            "triglycerides": "triglycerides",
            "tsh": "tsh",
            "vitamina_d": "vitamin_d",
            "vitamin_d": "vitamin_d",
            "b12": "b12",
            "ferritina": "ferritin",
            "ferritin": "ferritin",
        }

        marker_aliases = {
            "glucose",
            "insulin",
            "hba1c",
            "total_cholesterol",
            "hdl",
            "ldl",
            "triglycerides",
            "tsh",
            "vitamin_d",
            "b12",
            "ferritin",
        }

        def _get_canonical(key: str) -> str | None:
            if key in mapping:
                return mapping[key]
            normalized = _normalize_key(key)
            if normalized in local_aliases:
                return local_aliases[normalized]
            return MEDICAL_LAB_ALIASES.get(normalized)

        def _number_or_raw(value: Any) -> Any:
            number = self._coerce_number(value)
            if number is None:
                return value
            return float(number)

        def _apply_marker_field(
            marker: dict[str, Any],
            canonical: str | None,
            value: Any,
        ) -> None:
            if not canonical:
                return
            if canonical == "name":
                marker["name"] = str(value)
            elif canonical == "value":
                marker["value"] = _number_or_raw(value)
            elif canonical == "unit":
                marker["unit"] = str(value)
            elif canonical == "reference_range":
                marker["reference_text"] = str(value)
            elif canonical == "status":
                marker["status"] = str(value).lower()
            elif canonical == "notes":
                marker["notes"] = str(value)
            elif canonical == "code":
                marker["code"] = str(value)

        documents: list[dict[str, Any]] = []
        warnings: list[str] = []

        for index, record in enumerate(records):
            document: dict[str, Any] = {
                "schema_version": "1.0",
                "type": "medical_lab",
                "user_id": user_id,
                "source_type": source_type,
                "markers": [],
            }
            markers_source: Any = None

            for source_field, value in record.items():
                canonical = _get_canonical(source_field)

                if canonical in marker_aliases:
                    marker: dict[str, Any] = {"name": canonical}
                    if isinstance(value, dict):
                        for marker_field, marker_value in value.items():
                            _apply_marker_field(
                                marker,
                                _get_canonical(marker_field),
                                marker_value,
                            )
                    else:
                        marker["value"] = _number_or_raw(value)
                    document["markers"].append(self._drop_none(marker))
                    continue

                if canonical == "lab_date":
                    document["date"] = str(value)
                elif canonical == "lab_name":
                    document["laboratory_name"] = str(value)
                elif canonical == "markers":
                    markers_source = value
                elif canonical == "notes":
                    document["notes"] = str(value)

            if isinstance(markers_source, list):
                for marker_item in markers_source:
                    if not isinstance(marker_item, dict):
                        continue

                    marker: dict[str, Any] = {}
                    for source_field, value in marker_item.items():
                        canonical = _get_canonical(source_field)
                        _apply_marker_field(marker, canonical, value)

                    if marker:
                        document["markers"].append(self._drop_none(marker))

            document = self._drop_none(document)
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
    def _medical_lab_parent_path(path: str) -> str | None:
        marker_roots = {"marcadores", "markers", "analitos"}
        marker_suffixes = (".marcadores", ".markers", ".analitos")

        if path in marker_roots:
            return "$"

        for suffix in marker_suffixes:
            if path.endswith(suffix):
                parent_path = path[: -len(suffix)]
                return parent_path or "$"

        return None

    @staticmethod
    def _medical_lab_source_type(source_type: str) -> str:
        if source_type in {"manual_generated", "uploaded"}:
            return source_type
        return "uploaded"

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
