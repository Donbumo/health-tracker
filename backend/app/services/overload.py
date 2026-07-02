from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise, TrainingSet


RIR_FOR_LOAD_INCREASE = Decimal("2")


def _set_volume(training_set: TrainingSet) -> Decimal:
    return training_set.weight_kg * training_set.reps


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
        "volume": _set_volume(best),
    }


def exercise_metrics(exercise: TrainingSessionExercise) -> dict[str, Any]:
    sets = list(exercise.sets)
    return {
        "exercise_id": exercise.id,
        "session_id": exercise.training_session_id,
        "performed_at": exercise.training_session.performed_at,
        "volume": sum((_set_volume(item) for item in sets), Decimal("0")),
        "total_reps": sum(item.reps for item in sets),
        "max_weight": max((item.weight_kg for item in sets), default=Decimal("0")),
        "best_set": _best_set(sets),
    }


def session_metrics(training_session: TrainingSession) -> dict[str, Any]:
    all_sets = [item for exercise in training_session.exercises for item in exercise.sets]
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
            "progress_detected": False,
        }

    volume_delta = current["volume"] - previous["volume"]
    reps_delta = current["total_reps"] - previous["total_reps"]
    max_weight_delta = current["max_weight"] - previous["max_weight"]
    return {
        "has_previous": True,
        "volume_delta": volume_delta,
        "reps_delta": reps_delta,
        "max_weight_delta": max_weight_delta,
        "progress_detected": (
            volume_delta > 0 or reps_delta > 0 or max_weight_delta > 0
        ),
    }


def exercise_history(user_id: int, exercise_name: str) -> list[dict[str, Any]]:
    exercises = db.session.execute(
        db.select(TrainingSessionExercise).where(
            TrainingSessionExercise.user_id == user_id
        )
    ).scalars()
    matching = [
        exercise
        for exercise in exercises
        if exercise.name.casefold() == exercise_name.casefold()
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
    for exercise in matching:
        current_metrics = exercise_metrics(exercise)
        history.append(
            {
                "exercise": exercise,
                "metrics": current_metrics,
                "comparison": _comparison(current_metrics, previous_metrics),
                "suggestion": overload_suggestion(exercise),
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
    }
