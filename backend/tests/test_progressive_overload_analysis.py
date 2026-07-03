import io
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import TrainingSession, User
from app.services.overload import (
    exercise_history,
    exercise_metrics,
    estimated_one_rep_max,
    session_metrics,
    session_progress_summary,
)
from app.services.workout_sessions import list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _setup_plan(app, client, user_id: int) -> str:
    login(client)
    payload = json.dumps(training_plan_document(user_id)).encode("utf-8")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "progress-analysis-plan.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        return list_planned_days(user_id)[0].key


def _session_form(
    planned_day: str,
    performed_at: str,
    *,
    weight: str,
    reps: str,
    rpe_values: tuple[str, str] | None = None,
    rest_values: tuple[str, str] | None = None,
    include_session_context: bool = False,
) -> dict[str, str]:
    data = {
        "planned_day": planned_day,
        "performed_at": performed_at,
        "notes": "Fictional progressive overload analysis",
    }
    if include_session_context:
        data.update(
            {
                "duration_minutes": "60",
                "average_heart_rate_bpm": "138",
                "calories_burned": "410.50",
            }
        )
    for set_index in range(2):
        prefix = f"exercise_0_set_{set_index}"
        data[f"{prefix}_completed"] = "1"
        data[f"{prefix}_weight_kg"] = weight
        data[f"{prefix}_reps"] = reps
        data[f"{prefix}_rir"] = "1"
        if rpe_values is not None:
            data[f"{prefix}_rpe"] = rpe_values[set_index]
        if rest_values is not None:
            data[f"{prefix}_rest_seconds"] = rest_values[set_index]
    return data


def _create_session(client, planned_day: str, performed_at: str, **values) -> None:
    response = client.post(
        "/training-sessions/new",
        data=_session_form(planned_day, performed_at, **values),
    )
    assert response.status_code == 302


def test_epley_estimate_and_optional_recovery_metrics(app, client, user):
    planned_day = _setup_plan(app, client, user)
    _create_session(
        client,
        planned_day,
        "2026-07-01T18:00",
        weight="100",
        reps="10",
        rpe_values=("8", "9"),
        rest_values=("90", "120"),
        include_session_context=True,
    )

    with app.app_context():
        training_session = db.session.execute(db.select(TrainingSession)).scalar_one()
        exercise = training_session.exercises[0]
        metrics = exercise_metrics(exercise)
        totals = session_metrics(training_session)
        exercise_id = exercise.id
        session_id = training_session.id

        assert estimated_one_rep_max(exercise.sets[0]) == Decimal("133.33")
        assert metrics["best_estimated_one_rep_max"] == Decimal("133.33")
        assert metrics["average_rpe"] == Decimal("8.50")
        assert metrics["average_rest_seconds"] == Decimal("105.00")
        assert totals["duration_seconds"] == 3600
        assert totals["average_heart_rate_bpm"] == 138
        assert totals["calories_burned"] == Decimal("410.50")

    exercise_view = client.get(f"/progress/exercises/{exercise_id}")
    assert exercise_view.status_code == 200
    assert b"1RM estimado" in exercise_view.data
    assert b"RPE promedio" in exercise_view.data
    assert b"Descanso promedio" in exercise_view.data

    session_view = client.get(f"/progress/sessions/{session_id}")
    assert session_view.status_code == 200
    assert b"3600 segundos" in session_view.data
    assert b"133.33" in session_view.data


def test_history_compares_estimated_one_rep_max_and_detects_progress(
    app,
    client,
    user,
):
    planned_day = _setup_plan(app, client, user)
    _create_session(
        client,
        planned_day,
        "2026-07-01T18:00",
        weight="50",
        reps="6",
    )
    _create_session(
        client,
        planned_day,
        "2026-07-08T18:00",
        weight="55",
        reps="7",
    )

    with app.app_context():
        history = exercise_history(user, "EXAMPLE SQUAT")
        assert len(history) == 2
        current = history[-1]
        assert current["metrics"]["best_estimated_one_rep_max"] == Decimal("67.83")
        assert current["comparison"]["estimated_one_rep_max_delta"] == Decimal(
            "7.83"
        )
        assert current["comparison"]["progress_detected"] is True
        assert current["stagnation"]["detected"] is False


def test_three_unchanged_appearances_detect_stagnation(app, client, user):
    planned_day = _setup_plan(app, client, user)
    for day in (1, 8, 15):
        _create_session(
            client,
            planned_day,
            f"2026-07-{day:02d}T18:00",
            weight="50",
            reps="8",
        )

    with app.app_context():
        history = exercise_history(user, "Example squat")
        latest = history[-1]
        session_id = latest["exercise"].training_session_id
        assert history[-2]["stagnation"]["detected"] is False
        assert latest["stagnation"]["detected"] is True
        assert latest["stagnation"]["appearances"] == 3
        assert session_progress_summary(
            latest["exercise"].training_session,
            user,
        )["stagnation_detected"] is True

    response = client.get(f"/progress/sessions/{session_id}")
    assert response.status_code == 200
    assert b"Estancamiento" in response.data


def test_high_rpe_with_strong_drop_detects_fatigue(app, client, user):
    planned_day = _setup_plan(app, client, user)
    _create_session(
        client,
        planned_day,
        "2026-07-01T18:00",
        weight="50",
        reps="8",
        rpe_values=("8", "8"),
    )
    _create_session(
        client,
        planned_day,
        "2026-07-08T18:00",
        weight="50",
        reps="5",
        rpe_values=("9.5", "9.5"),
    )

    with app.app_context():
        latest = exercise_history(user, "Example squat")[-1]
        assert latest["fatigue"]["detected"] is True
        assert latest["fatigue"]["volume_drop_percent"] == Decimal("37.5")
        assert latest["fatigue"]["reps_drop_percent"] == Decimal("37.5")
        assert session_progress_summary(
            latest["exercise"].training_session,
            user,
        )["fatigue_detected"] is True


def test_missing_rpe_and_rest_remain_compatible_and_user_isolated(
    app,
    client,
    user,
):
    planned_day = _setup_plan(app, client, user)
    _create_session(
        client,
        planned_day,
        "2026-07-01T18:00",
        weight="50",
        reps="8",
    )

    with app.app_context():
        training_session = db.session.execute(db.select(TrainingSession)).scalar_one()
        exercise = training_session.exercises[0]
        metrics = exercise_metrics(exercise)
        session_id = training_session.id
        exercise_id = exercise.id

        assert metrics["average_rpe"] is None
        assert metrics["average_rest_seconds"] is None
        assert exercise_history(user, exercise.name)[0]["fatigue"]["detected"] is False

        second = User(username="overload-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        assert exercise_history(second_id, exercise.name) == []
        with pytest.raises(ValueError):
            session_progress_summary(training_session, second_id)

    client.post("/logout")
    login(client, "overload-second-user", "second-password")
    assert client.get(f"/progress/sessions/{session_id}").status_code == 404
    assert client.get(f"/progress/exercises/{exercise_id}").status_code == 404
