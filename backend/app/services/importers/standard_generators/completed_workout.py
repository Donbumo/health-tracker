"""Standard JSON generation for assisted completed workout candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_datetime,
    coerce_number,
    drop_none,
)
from app.services.importers.standard_generators.weigh_in import (
    normalize_source_type,
)
from app.services.importers.universal_json_import_assistant import (
    COMPLETED_WORKOUT_ALIASES,
    _normalize_key,
)


SCHEMA_NAME = "completed_workout"

LOCAL_ALIASES = {
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
    "detalle_carga": "load_details",
    "load_details": "load_details",
    "reps": "reps",
    "rir": "rir",
    "rpe": "rpe",
    "descanso": "rest_seconds",
    "rest_seconds": "rest_seconds",
}


def generate(
    *,
    records: list[dict[str, Any]],
    mapping: dict[str, str],
    user_id: int,
    source_type: str,
    default_timezone: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate completed_workout documents from an assisted candidate mapping.

    This function must not invent required plan, exercise, or set values.
    If required fields are missing, the generated document remains invalid
    and validation reports the missing fields.
    """

    documents: list[dict[str, Any]] = []
    warnings: list[str] = []

    for record in records:
        data: dict[str, Any] = {}
        pending_date_value: Any = None
        pending_time: Any = None
        exercises_source: Any = None

        for source_field, value in record.items():
            canonical = _get_canonical(source_field, mapping)
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
            data["performed_at"] = coerce_datetime(
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
                    canonical = _get_canonical(source_field, mapping)
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
                            canonical = _get_canonical(source_field, mapping)
                            if not canonical:
                                continue

                            if canonical == "set_number":
                                set_data["set_number"] = _int_or_none(value)
                            elif canonical == "planned_set_number":
                                set_data["planned_set_number"] = _int_or_none(value)
                            elif canonical == "weight_kg":
                                set_data["weight_kg"] = _float_or_none(value)
                            elif canonical == "load_details" and isinstance(value, dict):
                                set_data["load_details"] = value
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

                        sets.append(drop_none(set_data))

                ex_data["sets"] = sets
                exercises.append(drop_none(ex_data))

        data["exercises"] = exercises

        documents.append(
            {
                "schema_version": "1.0",
                "record_type": "completed_workout",
                "user_id": user_id,
                "source_type": source_type,
                "data": drop_none(data),
            }
        )

    return documents, warnings


def _get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return mapping[key]
    normalized = _normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]
    return COMPLETED_WORKOUT_ALIASES.get(normalized)


def _int_or_none(value: Any) -> int | None:
    number = coerce_number(value)
    if number is None:
        return None
    return int(number)


def _float_or_none(value: Any) -> float | None:
    number = coerce_number(value)
    if number is None:
        return None
    return float(number)
