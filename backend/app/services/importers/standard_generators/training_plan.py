"""Standard JSON generation for assisted training plan candidates."""

from __future__ import annotations

from typing import Any

from app.services.importers.standard_generators.common import (
    coerce_number,
    drop_none,
)
from app.services.importers.universal_json_import_assistant import (
    TRAINING_PLAN_ALIASES,
    _normalize_key,
)


SCHEMA_NAME = "training_plan"

ALLOWED_SOURCE_TYPES = {"uploaded", "manual_generated"}

LOCAL_ALIASES = {
    "plan": "name",
    "rutina": "name",
    "programa": "name",
    "nombre": "name",
    "name": "name",
    "descripcion": "description",
    "description": "description",
    "semanas": "weeks",
    "weeks": "weeks",
    "semana": "week_number",
    "week": "week_number",
    "week_number": "week_number",
    "dias": "days",
    "days": "days",
    "dia": "day_number",
    "day": "day_number",
    "day_number": "day_number",
    "ejercicios": "exercises",
    "exercises": "exercises",
    "orden": "exercise_order",
    "exercise_order": "exercise_order",
    "notas": "notes",
    "notes": "notes",
    "series": "sets",
    "series_objetivo": "sets",
    "sets": "sets",
    "serie": "set_number",
    "set": "set_number",
    "set_number": "set_number",
    "reps": "reps",
    "repeticiones": "reps",
    "reps_objetivo": "reps",
    "reps_min": "reps_min",
    "reps_max": "reps_max",
    "rir_objetivo": "rir",
    "rpe_objetivo": "rpe",
    "duracion_segundos": "duration_seconds",
    "duration_seconds": "duration_seconds",
    "distancia_m": "distance_m",
    "distance_m": "distance_m",
    "objetivo": "target",
    "target": "target",
    "descanso": "rest_seconds",
    "descanso_objetivo": "rest_seconds",
    "rest_seconds": "rest_seconds",
    "version": "version",
    "bloques": "blocks",
}

PLAN_FIELDS = {"name", "description"}
WEEK_FIELDS = {"week_number", "name"}
DAY_FIELDS = {"day_number", "name"}
EXERCISE_FIELDS = {"exercise_order", "name", "notes"}
SET_FIELDS = {
    "set_number",
    "reps",
    "reps_min",
    "reps_max",
    "duration_seconds",
    "distance_m",
    "target",
    "rest_seconds",
}

INTEGER_FIELDS = {
    "week_number",
    "day_number",
    "exercise_order",
    "set_number",
    "reps",
    "reps_min",
    "reps_max",
    "duration_seconds",
    "rest_seconds",
}

NUMBER_FIELDS = INTEGER_FIELDS | {"distance_m"}

NESTED_PLAN_SEGMENTS = (
    ".weeks",
    ".semanas",
    ".days",
    ".dias",
    ".exercises",
    ".ejercicios",
    ".sets",
    ".series",
)
ROOT_PLAN_SEGMENTS = {
    "weeks",
    "semanas",
    "days",
    "dias",
    "exercises",
    "ejercicios",
    "sets",
    "series",
}


def normalize_source_type(source_type: str) -> str:
    if source_type in ALLOWED_SOURCE_TYPES:
        return source_type
    return "uploaded"


def parent_path(path: str) -> str | None:
    """Return the training plan parent path for nested plan candidates."""

    if path in ROOT_PLAN_SEGMENTS:
        return "$"

    first_index: int | None = None
    for segment in NESTED_PLAN_SEGMENTS:
        index = path.find(segment)
        if index > 0 and (first_index is None or index < first_index):
            first_index = index

    if first_index is not None:
        return path[:first_index] or "$"

    return None


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
        data: dict[str, Any] = {}
        weeks_source: Any = None

        for source_field, value in record.items():
            canonical = _get_canonical(source_field, mapping)
            if canonical == "weeks":
                weeks_source = value
            elif canonical == "days":
                weeks_source = [{"days": value}]
            elif canonical in PLAN_FIELDS:
                data[canonical] = value
            elif canonical is not None:
                warnings.append(
                    f"record {index}: unsupported training_plan field ignored: "
                    f"{canonical} (from source: {source_field})"
                )
            else:
                warnings.append(
                    f"record {index}: unknown training_plan source field ignored: "
                    f"{source_field}"
                )

        if weeks_source is not None:
            data["weeks"] = _weeks_from_source(
                weeks_source,
                mapping=mapping,
                warnings=warnings,
                record_index=index,
            )

        documents.append(
            {
                "schema_version": "1.0",
                "record_type": "training_plan",
                "user_id": user_id,
                "source_type": normalize_source_type(source_type),
                "data": drop_none(data),
            }
        )

    return documents, warnings


def _get_canonical(key: str, mapping: dict[str, str]) -> str | None:
    if key in mapping:
        return _schema_alias(mapping[key])

    normalized = _normalize_key(key)
    if normalized in LOCAL_ALIASES:
        return LOCAL_ALIASES[normalized]

    alias = TRAINING_PLAN_ALIASES.get(normalized)
    if alias is not None:
        return _schema_alias(alias)

    return None


def _schema_alias(canonical: str) -> str:
    return LOCAL_ALIASES.get(_normalize_key(canonical), canonical)


def _weeks_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        week_records = [value]
    elif isinstance(value, list):
        week_records = [item for item in value if isinstance(item, dict)]
    else:
        warnings.append(
            f"record {record_index}: training_plan weeks ignored because it is not a list"
        )
        return []

    return [
        _week_from_object(
            week,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
        )
        for week_index, week in enumerate(week_records)
    ]


def _week_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
) -> dict[str, Any]:
    week: dict[str, Any] = {}
    days_source: Any = None

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        if canonical == "days":
            days_source = field_value
        elif canonical in WEEK_FIELDS:
            _apply_field(week, canonical, field_value)
        elif canonical is not None:
            warnings.append(
                f"record {record_index}, week {week_index}: unsupported "
                f"training_plan week field ignored: {canonical}"
            )

    if days_source is not None:
        week["days"] = _days_from_source(
            days_source,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
        )

    return drop_none(week)


def _days_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        day_records = [value]
    elif isinstance(value, list):
        day_records = [item for item in value if isinstance(item, dict)]
    else:
        warnings.append(
            f"record {record_index}, week {week_index}: training_plan days "
            "ignored because it is not a list"
        )
        return []

    return [
        _day_from_object(
            day,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
            day_index=day_index,
        )
        for day_index, day in enumerate(day_records)
    ]


def _day_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
    day_index: int,
) -> dict[str, Any]:
    day: dict[str, Any] = {}
    exercises_source: Any = None

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        if canonical == "exercises":
            exercises_source = field_value
        elif canonical in DAY_FIELDS:
            _apply_field(day, canonical, field_value)
        elif canonical is not None:
            warnings.append(
                f"record {record_index}, week {week_index}, day {day_index}: "
                f"unsupported training_plan day field ignored: {canonical}"
            )

    if exercises_source is not None:
        day["exercises"] = _exercises_from_source(
            exercises_source,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
            day_index=day_index,
        )

    return drop_none(day)


def _exercises_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
    day_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        exercise_records = [value]
    elif isinstance(value, list):
        exercise_records = [item for item in value if isinstance(item, dict)]
    else:
        warnings.append(
            f"record {record_index}, week {week_index}, day {day_index}: "
            "training_plan exercises ignored because it is not a list"
        )
        return []

    return [
        _exercise_from_object(
            exercise,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
            day_index=day_index,
            exercise_index=exercise_index,
        )
        for exercise_index, exercise in enumerate(exercise_records)
    ]


def _exercise_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
    day_index: int,
    exercise_index: int,
) -> dict[str, Any]:
    exercise: dict[str, Any] = {}
    sets_source: Any = None

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        if canonical == "sets":
            sets_source = field_value
        elif canonical in EXERCISE_FIELDS:
            _apply_field(exercise, canonical, field_value)
        elif canonical is not None:
            warnings.append(
                f"record {record_index}, week {week_index}, day {day_index}, "
                f"exercise {exercise_index}: unsupported training_plan exercise "
                f"field ignored: {canonical}"
            )

    if sets_source is not None:
        exercise["sets"] = _sets_from_source(
            sets_source,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
            day_index=day_index,
            exercise_index=exercise_index,
        )

    return drop_none(exercise)


def _sets_from_source(
    value: Any,
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
    day_index: int,
    exercise_index: int,
) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        set_records = [value]
    elif isinstance(value, list):
        set_records = [item for item in value if isinstance(item, dict)]
    else:
        warnings.append(
            f"record {record_index}, week {week_index}, day {day_index}, "
            f"exercise {exercise_index}: training_plan sets ignored because it is not a list"
        )
        return []

    return [
        _set_from_object(
            set_item,
            mapping=mapping,
            warnings=warnings,
            record_index=record_index,
            week_index=week_index,
            day_index=day_index,
            exercise_index=exercise_index,
            set_index=set_index,
        )
        for set_index, set_item in enumerate(set_records)
    ]


def _set_from_object(
    value: dict[str, Any],
    *,
    mapping: dict[str, str],
    warnings: list[str],
    record_index: int,
    week_index: int,
    day_index: int,
    exercise_index: int,
    set_index: int,
) -> dict[str, Any]:
    set_data: dict[str, Any] = {}

    for source_field, field_value in value.items():
        canonical = _get_canonical(source_field, mapping)
        if canonical in SET_FIELDS:
            _apply_field(set_data, canonical, field_value)
        elif canonical is not None:
            warnings.append(
                f"record {record_index}, week {week_index}, day {day_index}, "
                f"exercise {exercise_index}, set {set_index}: unsupported "
                f"training_plan set field ignored: {canonical}"
            )

    return drop_none(set_data)


def _apply_field(target: dict[str, Any], canonical: str, value: Any) -> None:
    if canonical in NUMBER_FIELDS:
        number = coerce_number(value)
        if canonical in INTEGER_FIELDS and number is not None:
            target[canonical] = int(number)
        else:
            target[canonical] = number
    else:
        target[canonical] = value
