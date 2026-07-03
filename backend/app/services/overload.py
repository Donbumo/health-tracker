from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise, TrainingSet
from app.services.exercise_identity import (
    exercise_identity_names,
    find_exercise_identity,
    normalize_exercise_name,
)


RIR_FOR_LOAD_INCREASE = Decimal("2")
HIGH_RPE_THRESHOLD = Decimal("9")
STRONG_DROP_RATIO = Decimal("0.10")
STAGNATION_APPEARANCES = 3
TWO_DECIMAL_PLACES = Decimal("0.01")
ONE_DECIMAL_PLACE = Decimal("0.1")


def _set_volume(training_set: TrainingSet) -> Decimal:
    return training_set.weight_kg * training_set.reps


def estimated_one_rep_max(training_set: TrainingSet) -> Decimal:
    """Estimate one-repetition maximum with the Epley formula."""
    estimate = training_set.weight_kg * (
        Decimal("1") + (Decimal(training_set.reps) / Decimal("30"))
    )
    return estimate.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        TWO_DECIMAL_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _best_set(sets: list[TrainingSet]) -> dict[str, Any] | None:
    if not sets:
        return None
    best = max(
        sets,
        key=lambda item: (_set_volume(item), item.weight_kg, item.reps),
    )
    return {
        "set_id": best.id,
        "weight_kg": best.weight_kg,
        "reps": best.reps,
        "rir": best.rir,
        "rpe": best.rpe,
        "rest_seconds": best.rest_seconds,
        "volume": _set_volume(best),
        "estimated_one_rep_max": estimated_one_rep_max(best),
    }


def exercise_metrics(exercise: TrainingSessionExercise) -> dict[str, Any]:
    sets = list(exercise.sets)
    rpe_values = [item.rpe for item in sets if item.rpe is not None]
    rest_values = [
        Decimal(item.rest_seconds)
        for item in sets
        if item.rest_seconds is not None
    ]
    return {
        "exercise_id": exercise.id,
        "session_id": exercise.training_session_id,
        "performed_at": exercise.training_session.performed_at,
        "volume": sum((_set_volume(item) for item in sets), Decimal("0")),
        "total_reps": sum(item.reps for item in sets),
        "max_weight": max((item.weight_kg for item in sets), default=Decimal("0")),
        "best_estimated_one_rep_max": max(
            (estimated_one_rep_max(item) for item in sets),
            default=Decimal("0"),
        ),
        "average_rpe": _average(rpe_values),
        "average_rest_seconds": _average(rest_values),
        "best_set": _best_set(sets),
    }


def session_metrics(training_session: TrainingSession) -> dict[str, Any]:
    all_sets = [
        item
        for exercise in training_session.exercises
        for item in exercise.sets
    ]
    rpe_values = [item.rpe for item in all_sets if item.rpe is not None]
    rest_values = [
        Decimal(item.rest_seconds)
        for item in all_sets
        if item.rest_seconds is not None
    ]
    best = _best_set(all_sets)
    if best:
        best_set_id = best["set_id"]
        best_exercise = next(
            exercise
            for exercise in training_session.exercises
            if any(item.id == best_set_id for item in exercise.sets)
        )
        best["exercise_name"] = best_exercise.name

    return {
        "volume": sum((_set_volume(item) for item in all_sets), Decimal("0")),
        "total_reps": sum(item.reps for item in all_sets),
        "max_weight": max(
            (item.weight_kg for item in all_sets),
            default=Decimal("0"),
        ),
        "best_estimated_one_rep_max": max(
            (estimated_one_rep_max(item) for item in all_sets),
            default=Decimal("0"),
        ),
        "average_rpe": _average(rpe_values),
        "average_rest_seconds": _average(rest_values),
        "duration_seconds": training_session.duration_seconds,
        "average_heart_rate_bpm": training_session.average_heart_rate_bpm,
        "calories_burned": training_session.calories_burned,
        "best_set": best,
    }


def _planned_exercise(exercise: TrainingSessionExercise) -> dict[str, Any]:
    training_session = exercise.training_session
    for week in training_session.training_plan_version.content["data"]["weeks"]:
        if week["week_number"] != training_session.planned_week_number:
            continue
        for day in week["days"]:
            if day["day_number"] != training_session.planned_day_number:
                continue
            for planned in day["exercises"]:
                if planned["exercise_order"] == exercise.planned_exercise_order:
                    return planned
    raise RuntimeError("Planned exercise is missing from the session plan version")


def _target_range(planned_set: dict[str, Any]) -> tuple[int, int] | None:
    if planned_set.get("reps_min") is not None:
        return planned_set["reps_min"], planned_set["reps_max"]
    if planned_set.get("reps") is not None:
        return planned_set["reps"], planned_set["reps"]
    return None


def overload_suggestion(exercise: TrainingSessionExercise) -> dict[str, str]:
    planned = _planned_exercise(exercise)
    actual_by_planned_set = {
        item.planned_set_number: item for item in exercise.sets
    }
    rep_targets = 0
    all_at_high_with_reserve = True

    for planned_set in planned["sets"]:
        actual = actual_by_planned_set.get(planned_set["set_number"])
        if actual is None:
            return {
                "code": "review_fatigue",
                "label": "Revisar fatiga",
                "reason": "Faltaron una o más series planeadas.",
            }

        target_range = _target_range(planned_set)
        if target_range is None:
            all_at_high_with_reserve = False
            continue
        rep_targets += 1
        minimum, maximum = target_range
        if actual.reps < minimum:
            return {
                "code": "review_fatigue",
                "label": "Revisar fatiga",
                "reason": "Las reps reales quedaron por debajo del rango planeado.",
            }
        if (
            actual.reps < maximum
            or actual.rir is None
            or actual.rir < RIR_FOR_LOAD_INCREASE
        ):
            all_at_high_with_reserve = False

    if rep_targets and all_at_high_with_reserve:
        return {
            "code": "increase_load",
            "label": "Subir carga",
            "reason": "Se alcanzó el rango alto con al menos 2 RIR en todas las series.",
        }
    return {
        "code": "maintain",
        "label": "Mantener",
        "reason": "El trabajo está dentro del rango, sin margen suficiente para subir carga.",
    }


def _comparison(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if previous is None:
        return {
            "has_previous": False,
            "volume_delta": None,
            "reps_delta": None,
            "max_weight_delta": None,
            "estimated_one_rep_max_delta": None,
            "progress_detected": False,
        }

    volume_delta = current["volume"] - previous["volume"]
    reps_delta = current["total_reps"] - previous["total_reps"]
    max_weight_delta = current["max_weight"] - previous["max_weight"]
    estimated_one_rep_max_delta = (
        current["best_estimated_one_rep_max"]
        - previous["best_estimated_one_rep_max"]
    )
    return {
        "has_previous": True,
        "volume_delta": volume_delta,
        "reps_delta": reps_delta,
        "max_weight_delta": max_weight_delta,
        "estimated_one_rep_max_delta": estimated_one_rep_max_delta,
        "progress_detected": (
            volume_delta > 0
            or reps_delta > 0
            or max_weight_delta > 0
            or estimated_one_rep_max_delta > 0
        ),
    }


def _drop_percentage(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous <= 0 or current >= previous:
        return None
    return (
        ((previous - current) / previous) * Decimal("100")
    ).quantize(ONE_DECIMAL_PLACE, rounding=ROUND_HALF_UP)


def _fatigue_signal(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    average_rpe = current["average_rpe"]
    if previous is None or average_rpe is None or average_rpe < HIGH_RPE_THRESHOLD:
        return {
            "detected": False,
            "reason": None,
            "volume_drop_percent": None,
            "reps_drop_percent": None,
        }

    volume_drop = _drop_percentage(current["volume"], previous["volume"])
    reps_drop = _drop_percentage(
        Decimal(current["total_reps"]),
        Decimal(previous["total_reps"]),
    )
    strong_volume_drop = (
        volume_drop is not None
        and volume_drop >= STRONG_DROP_RATIO * Decimal("100")
    )
    strong_reps_drop = (
        reps_drop is not None
        and reps_drop >= STRONG_DROP_RATIO * Decimal("100")
    )
    detected = strong_volume_drop or strong_reps_drop
    return {
        "detected": detected,
        "reason": (
            "RPE promedio alto junto con una caída de al menos 10% en reps o volumen."
            if detected
            else None
        ),
        "volume_drop_percent": volume_drop,
        "reps_drop_percent": reps_drop,
    }


def _stagnation_signal(appearances_without_progress: int) -> dict[str, Any]:
    detected = appearances_without_progress >= STAGNATION_APPEARANCES
    return {
        "detected": detected,
        "appearances": appearances_without_progress,
        "reason": (
            "No mejoraron peso, reps, volumen ni 1RM estimado en al menos "
            f"{STAGNATION_APPEARANCES} apariciones consecutivas."
            if detected
            else None
        ),
    }


def _comparison_trend(comparison: dict[str, Any]) -> dict[str, str]:
    if not comparison["has_previous"]:
        return {"code": "baseline", "label": "Primera sesión"}

    deltas = (
        comparison["volume_delta"],
        comparison["reps_delta"],
        comparison["max_weight_delta"],
        comparison["estimated_one_rep_max_delta"],
    )
    has_improvement = any(delta > 0 for delta in deltas)
    has_decline = any(delta < 0 for delta in deltas)
    if has_improvement and has_decline:
        return {"code": "mixed", "label": "Tendencia mixta"}
    if has_improvement:
        return {"code": "improved", "label": "Mejora"}
    if has_decline:
        return {"code": "declined", "label": "Baja"}
    return {"code": "stable", "label": "Sin cambio"}


def _effective_recommendation(
    suggestion: dict[str, str],
    stagnation: dict[str, Any],
    fatigue: dict[str, Any],
) -> dict[str, str]:
    if fatigue["detected"]:
        return {
            "code": "review_fatigue",
            "label": "Revisar fatiga",
            "reason": fatigue["reason"],
        }
    if stagnation["detected"]:
        return {
            "code": "possible_stagnation",
            "label": "Posible estancamiento",
            "reason": stagnation["reason"],
        }
    return suggestion


def exercise_history(user_id: int, exercise_name: str) -> list[dict[str, Any]]:
    identity = find_exercise_identity(user_id, exercise_name)
    matching_names = (
        exercise_identity_names(identity)
        if identity is not None
        else {normalize_exercise_name(exercise_name)}
    )
    exercises = db.session.execute(
        db.select(TrainingSessionExercise).where(
            TrainingSessionExercise.user_id == user_id
        )
    ).scalars()
    matching = [
        exercise
        for exercise in exercises
        if normalize_exercise_name(exercise.name) in matching_names
        and exercise.training_session.user_id == user_id
    ]
    matching.sort(
        key=lambda exercise: (
            exercise.training_session.performed_at,
            exercise.training_session_id,
        )
    )

    history = []
    previous_metrics = None
    appearances_without_progress = 0
    for exercise in matching:
        current_metrics = exercise_metrics(exercise)
        comparison = _comparison(current_metrics, previous_metrics)
        if previous_metrics is None or comparison["progress_detected"]:
            appearances_without_progress = 1
        else:
            appearances_without_progress += 1
        stagnation = _stagnation_signal(appearances_without_progress)
        fatigue = _fatigue_signal(current_metrics, previous_metrics)
        suggestion = overload_suggestion(exercise)
        history.append(
            {
                "exercise": exercise,
                "metrics": current_metrics,
                "comparison": comparison,
                "trend": _comparison_trend(comparison),
                "stagnation": stagnation,
                "fatigue": fatigue,
                "suggestion": suggestion,
                "recommendation": _effective_recommendation(
                    suggestion,
                    stagnation,
                    fatigue,
                ),
            }
        )
        previous_metrics = current_metrics
    return history


def session_progress_summary(
    training_session: TrainingSession,
    user_id: int,
) -> dict[str, Any]:
    if training_session.user_id != user_id:
        raise ValueError("Training session does not belong to this user")

    exercise_rows = []
    for exercise in training_session.exercises:
        history = exercise_history(user_id, exercise.name)
        current = next(
            item for item in history if item["exercise"].id == exercise.id
        )
        exercise_rows.append(current)

    return {
        "metrics": session_metrics(training_session),
        "exercises": exercise_rows,
        "progress_detected": any(
            item["comparison"]["progress_detected"] for item in exercise_rows
        ),
        "stagnation_detected": any(
            item["stagnation"]["detected"] for item in exercise_rows
        ),
        "fatigue_detected": any(
            item["fatigue"]["detected"] for item in exercise_rows
        ),
    }
