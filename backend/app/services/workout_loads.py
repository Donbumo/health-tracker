"""Pure workout-load calculations plus transactional profile helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping
from sqlalchemy import and_, or_

from app.extensions import db
from app.models.exercise import Exercise, ExerciseAlias
from app.models.exercise_load_profile import ExerciseLoadProfile
from app.services.exercise_identity import find_exercise_identity, normalize_exercise_name


LB_TO_KG = Decimal("0.45359237")
MAX_WEIGHT = Decimal("2000")
LOAD_DETAIL_VERSION = "1.0"
CALCULATION_VERSION = "1.0"
SUPPORTED_UNITS = ("kg", "lb")
SUPPORTED_MODES = (
    "direct_total", "per_side", "bar_plus_per_side",
    "machine_initial_total", "machine_initial_per_side",
    "machine_external_per_side_initial_total", "selector_stack",
    "dumbbell_each", "bodyweight", "bodyweight_plus", "assistance",
    "duration_distance",
)
MODE_COMPONENTS = {
    "direct_total": ("direct_total",),
    "per_side": ("per_side",),
    "bar_plus_per_side": ("bar", "per_side"),
    "machine_initial_total": ("initial_total", "added_total"),
    "machine_initial_per_side": ("initial_per_side", "external_per_side"),
    "machine_external_per_side_initial_total": ("initial_total", "external_per_side"),
    "selector_stack": ("selector_stack",),
    "dumbbell_each": ("dumbbell_each",),
    "bodyweight": ("bodyweight",),
    "bodyweight_plus": ("bodyweight", "added_total"),
    "assistance": ("bodyweight", "assistance"),
    "duration_distance": ("duration_seconds", "distance_meters"),
}
LOAD_MODE_LABELS = {
    "direct_total": "Carga total",
    "per_side": "Por lado",
    "bar_plus_per_side": "Barra + por lado",
    "machine_initial_total": "Máquina: inicial total + añadido",
    "machine_initial_per_side": "Máquina: inicial y externo por lado",
    "machine_external_per_side_initial_total": "Máquina: inicial total + externo por lado",
    "selector_stack": "Pila selectora",
    "dumbbell_each": "Mancuerna por mano",
    "bodyweight": "Peso corporal",
    "bodyweight_plus": "Peso corporal + carga",
    "assistance": "Peso corporal con asistencia",
    "duration_distance": "Duración / distancia",
}
COMPONENT_LABELS = {
    "direct_total": "Total", "per_side": "Por lado", "bar": "Barra",
    "initial_total": "Inicial total", "added_total": "Añadido total",
    "initial_per_side": "Inicial por lado", "external_per_side": "Externo por lado",
    "selector_stack": "Pila", "dumbbell_each": "Cada mancuerna",
    "bodyweight": "Peso corporal", "assistance": "Asistencia",
    "duration_seconds": "Duración (s)", "distance_meters": "Distancia (m)",
}


class WorkoutLoadError(ValueError):
    pass


def _decimal(value: Any, field: str, *, maximum: Decimal = MAX_WEIGHT) -> Decimal:
    if value in (None, ""):
        raise WorkoutLoadError(f"{field} is required for this load mode")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise WorkoutLoadError(f"{field} must be a number") from error
    if not number.is_finite() or number < 0 or number > maximum:
        raise WorkoutLoadError(f"{field} is outside the allowed range")
    return number


def to_kg(value: Decimal, unit: str) -> Decimal:
    if unit not in SUPPORTED_UNITS:
        raise WorkoutLoadError("Unsupported load unit")
    return value if unit == "kg" else value * LB_TO_KG


def from_kg(value: Decimal, unit: str) -> Decimal:
    if unit not in SUPPORTED_UNITS:
        raise WorkoutLoadError("Unsupported load unit")
    return value if unit == "kg" else value / LB_TO_KG


def storage_weight(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


@dataclass(frozen=True)
class WorkoutLoadResult:
    total_kg: Decimal
    total_lb: Decimal
    details: dict[str, Any]

    @property
    def weight_kg(self) -> Decimal:
        return storage_weight(self.total_kg)


def _component(
    value: Any, name: str, default_unit: str
) -> tuple[Decimal, str, dict[str, str]]:
    fixed_unit = "s" if name == "duration_seconds" else "m" if name == "distance_meters" else None
    if isinstance(value, Mapping):
        if set(value) - {"value", "unit"}:
            raise WorkoutLoadError(f"{name} contains unsupported fields")
        raw_value = value.get("value")
        component_unit = str(value.get("unit") or fixed_unit or default_unit)
    else:
        raw_value = value
        component_unit = fixed_unit or default_unit
    if fixed_unit is not None:
        if component_unit != fixed_unit:
            raise WorkoutLoadError(f"{name} must use {fixed_unit}")
    elif component_unit not in SUPPORTED_UNITS:
        raise WorkoutLoadError(f"{name} uses an unsupported load unit")
    maximum = (
        Decimal("604800")
        if name == "duration_seconds"
        else Decimal("10000000")
        if name == "distance_meters"
        else MAX_WEIGHT
    )
    number = _decimal(raw_value, name, maximum=maximum)
    return number, component_unit, {
        "value": decimal_text(number),
        "unit": component_unit,
    }


def calculate_workout_load(mode: str, unit: str, components: Mapping[str, Any]) -> WorkoutLoadResult:
    if mode not in SUPPORTED_MODES:
        raise WorkoutLoadError("Unsupported load mode")
    if unit not in SUPPORTED_UNITS:
        raise WorkoutLoadError("Unsupported load unit")
    expected = MODE_COMPONENTS[mode]
    if set(components) - set(expected):
        raise WorkoutLoadError("Load components do not match the selected mode")
    parsed = {name: _component(components.get(name), name, unit) for name in expected}
    values = {name: item[0] for name, item in parsed.items()}
    component_units = {name: item[1] for name, item in parsed.items()}
    original_components = {name: item[2] for name, item in parsed.items()}
    values_kg = {
        name: (
            value
            if name in {"duration_seconds", "distance_meters"}
            else to_kg(value, component_units[name])
        )
        for name, value in values.items()
    }
    warnings: list[str] = []
    if mode == "direct_total": total_kg = values_kg["direct_total"]
    elif mode == "per_side": total_kg = values_kg["per_side"] * 2
    elif mode == "bar_plus_per_side": total_kg = values_kg["bar"] + values_kg["per_side"] * 2
    elif mode == "machine_initial_total": total_kg = values_kg["initial_total"] + values_kg["added_total"]
    elif mode == "machine_initial_per_side": total_kg = (values_kg["initial_per_side"] + values_kg["external_per_side"]) * 2
    elif mode == "machine_external_per_side_initial_total": total_kg = values_kg["initial_total"] + values_kg["external_per_side"] * 2
    elif mode == "selector_stack": total_kg = values_kg["selector_stack"]
    elif mode == "dumbbell_each": total_kg = values_kg["dumbbell_each"] * 2
    elif mode == "bodyweight": total_kg = values_kg["bodyweight"]
    elif mode == "bodyweight_plus": total_kg = values_kg["bodyweight"] + values_kg["added_total"]
    elif mode == "assistance":
        total_kg = max(values_kg["bodyweight"] - values_kg["assistance"], Decimal("0"))
        warnings.append("assistance_is_subtracted_from_bodyweight")
    else:
        total_kg = Decimal("0")
        warnings.append("duration_distance_has_no_normalized_weight")
    if total_kg > MAX_WEIGHT:
        raise WorkoutLoadError("Normalized load is outside the allowed range")
    total_lb = from_kg(total_kg, "lb")
    details: dict[str, Any] = {
        "schema_version": LOAD_DETAIL_VERSION,
        "load_mode": mode,
        "original_input": {
            "unit": unit,
            "components": original_components,
        },
        "original_unit": unit,
        "components": original_components,
        "normalized_total_kg": decimal_text(total_kg),
        "calculated_total_lb": decimal_text(total_lb),
        "display_total": {
            "value": decimal_text(from_kg(total_kg, unit)),
            "unit": unit,
        },
        "bodyweight_kg": (
            decimal_text(values_kg["bodyweight"])
            if "bodyweight" in values_kg
            else None
        ),
        "assistance": original_components.get("assistance"),
        "calculation_version": CALCULATION_VERSION,
    }
    if warnings: details["warnings"] = warnings
    return WorkoutLoadResult(total_kg, total_lb, details)


def validate_load_details(weight_kg: Any, details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if details is None:
        return None
    if (
        details.get("schema_version") != LOAD_DETAIL_VERSION
        or details.get("calculation_version") != CALCULATION_VERSION
    ):
        raise WorkoutLoadError("Unsupported load detail version")
    result = calculate_workout_load(
        str(details.get("load_mode")),
        str(details.get("original_unit")),
        details.get("components") or {},
    )
    if storage_weight(_decimal(weight_kg, "weight_kg")) != result.weight_kg:
        raise WorkoutLoadError("weight_kg does not match load details")
    if dict(details) != result.details:
        raise WorkoutLoadError("Load details do not match calculation semantics")
    return result.details


def validate_completed_workout_loads(document: Mapping[str, Any]) -> None:
    for exercise in (document.get("data") or document).get("exercises") or []:
        for training_set in exercise.get("sets") or []:
            validate_load_details(
                training_set.get("weight_kg"), training_set.get("load_details")
            )


def get_or_create_exercise_for_profile(user_id: int, name: str) -> Exercise:
    normalized = normalize_exercise_name(name)
    exercise = find_exercise_identity(user_id, name)
    if exercise is None:
        exercise = Exercise(user_id=user_id, canonical_name=name.strip(), normalized_name=normalized)
        db.session.add(exercise)
        db.session.flush()
    return exercise


def upsert_exercise_load_profile(*, user_id: int, exercise_name: str, load_details: Mapping[str, Any]) -> ExerciseLoadProfile:
    exercise = get_or_create_exercise_for_profile(user_id, exercise_name)
    profile = db.session.execute(db.select(ExerciseLoadProfile).where(
        ExerciseLoadProfile.user_id == user_id,
        ExerciseLoadProfile.exercise_id == exercise.id,
    )).scalar_one_or_none()
    if profile is None:
        profile = ExerciseLoadProfile(user_id=user_id, exercise_id=exercise.id)
        db.session.add(profile)
    is_new = profile.id is None
    profile.load_mode = str(load_details["load_mode"])
    profile.preferred_unit = str(load_details["original_unit"])
    profile.configuration_json = {
        "schema_version": LOAD_DETAIL_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "components": dict(load_details.get("components") or {}),
    }
    profile.revision = 1 if is_new else (profile.revision or 0) + 1
    return profile


def load_entry_defaults(user_id: int, exercise_names: list[str]) -> dict[str, dict[str, Any]]:
    """Load profiles and most-recent set in two bounded queries, never per exercise."""
    from app.models import TrainingSession, TrainingSessionExercise, TrainingSet

    normalized = {normalize_exercise_name(name): name for name in exercise_names}
    defaults = {name: {} for name in exercise_names}
    display_names = set(exercise_names)
    profiles = db.session.execute(
        db.select(
            ExerciseLoadProfile,
            Exercise,
            ExerciseAlias.normalized_name,
            ExerciseAlias.alias_name,
        )
        .select_from(Exercise)
        .outerjoin(
            ExerciseLoadProfile,
            and_(
                ExerciseLoadProfile.exercise_id == Exercise.id,
                ExerciseLoadProfile.user_id == user_id,
            ),
        ).outerjoin(
            ExerciseAlias, ExerciseAlias.exercise_id == Exercise.id
        ).where(
            Exercise.user_id == user_id,
            or_(
                Exercise.normalized_name.in_(normalized),
                ExerciseAlias.normalized_name.in_(normalized),
            ),
        )
    ).all()
    for profile, exercise, alias_name, alias_display in profiles:
        original = normalized.get(exercise.normalized_name) or normalized.get(alias_name)
        if original:
            normalized[exercise.normalized_name] = original
            display_names.add(exercise.canonical_name)
            if alias_name:
                normalized[alias_name] = original
            if alias_display:
                display_names.add(alias_display)
            if profile is not None:
                defaults[original]["profile"] = {
                    "load_mode": profile.load_mode,
                    "original_unit": profile.preferred_unit,
                    "components": (profile.configuration_json or {}).get("components", {}),
                    "revision": profile.revision,
                }
    recent = db.session.execute(
        db.select(TrainingSessionExercise.name, TrainingSet)
        .join(TrainingSession, TrainingSession.id == TrainingSessionExercise.training_session_id)
        .join(TrainingSet, TrainingSet.training_session_exercise_id == TrainingSessionExercise.id)
        .where(
            TrainingSessionExercise.user_id == user_id,
            TrainingSessionExercise.name.in_(display_names),
        )
        .order_by(TrainingSession.performed_at.desc(), TrainingSet.set_number.desc())
    ).all()
    seen: set[str] = set()
    for name, training_set in recent:
        key = normalize_exercise_name(name)
        original = normalized.get(key)
        if original is None or key in seen:
            continue
        seen.add(key)
        defaults[original]["last"] = training_set.load_details_json or calculate_workout_load(
            "direct_total",
            "kg",
            {"direct_total": training_set.weight_kg},
        ).details
    return defaults
