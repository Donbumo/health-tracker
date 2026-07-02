import io
import json
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise, User
from app.services.overload import (
    exercise_history,
    exercise_metrics,
    overload_suggestion,
    session_metrics,
    session_progress_summary,
)
from app.services.validation import validate_json_document
from app.services.workout_sessions import compare_plan_to_session, list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _range_plan_document(user_id: int) -> dict:
    document = training_plan_document(user_id)
    document["data"]["name"] = "Fictional Range Plan"
    planned_sets = document["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"]
    for planned_set in planned_sets:
        planned_set.pop("reps")
        planned_set["reps_min"] = 6
        planned_set["reps_max"] = 8
    return document


def _import_range_plan(client, user_id: int) -> None:
    document = _range_plan_document(user_id)
    payload = json.dumps(document).encode("utf-8")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "range-plan.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def _session_form(
    planned_day: str,
    performed_at: str,
    weight: str,
    reps: str,
    rir: str,
) -> dict[str, str]:
    data = {
        "planned_day": planned_day,
        "performed_at": performed_at,
        "notes": "Fictional overload test",
    }
    for set_index in range(2):
        prefix = f"exercise_0_set_{set_index}"
        data[f"{prefix}_completed"] = "1"
        data[f"{prefix}_weight_kg"] = weight
        data[f"{prefix}_reps"] = reps
        data[f"{prefix}_rir"] = rir
    return data


def _create_two_sessions(app, client, user):
    login(client)
    _import_range_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key

    client.post(
        "/training-sessions/new",
        data=_session_form(planned_day, "2026-07-01T18:00", "50", "7", "1"),
    )
    client.post(
        "/training-sessions/new",
        data=_session_form(planned_day, "2026-07-08T18:00", "55", "8", "2.5"),
    )
    return planned_day


def test_training_plan_schema_accepts_rep_range(app, user):
    with app.app_context():
        validate_json_document(_range_plan_document(user), "training_plan")


def test_overload_metrics_history_and_increase_suggestion(app, client, user):
    planned_day = _create_two_sessions(app, client, user)

    form_view = client.get(
        "/training-sessions/new",
        query_string={"planned_day": planned_day},
    )
    assert "6–8".encode() in form_view.data

    with app.app_context():
        sessions = db.session.execute(
            db.select(TrainingSession).order_by(TrainingSession.performed_at)
        ).scalars().all()
        first_exercise = sessions[0].exercises[0]
        current_exercise = sessions[1].exercises[0]
        exercise_id = current_exercise.id
        session_id = sessions[1].id

        current = exercise_metrics(current_exercise)
        assert current["volume"] == Decimal("880.00")
        assert current["total_reps"] == 16
        assert current["max_weight"] == Decimal("55.00")
        assert current["best_set"]["volume"] == Decimal("440.00")

        first_suggestion = overload_suggestion(first_exercise)
        assert first_suggestion["code"] == "maintain"
        assert overload_suggestion(current_exercise)["code"] == "increase_load"

        history = exercise_history(user, "example SQUAT")
        assert len(history) == 2
        assert history[0]["comparison"]["has_previous"] is False
        assert history[1]["comparison"]["volume_delta"] == Decimal("180.00")
        assert history[1]["comparison"]["reps_delta"] == 2
        assert history[1]["comparison"]["max_weight_delta"] == Decimal("5.00")
        assert history[1]["comparison"]["progress_detected"] is True

        total = session_metrics(sessions[1])
        assert total["volume"] == Decimal("880.00")
        assert total["total_reps"] == 16
        assert total["max_weight"] == Decimal("55.00")
        assert total["best_set"]["exercise_name"] == "Example squat"

        summary = session_progress_summary(sessions[1], user)
        assert summary["progress_detected"] is True
        assert summary["exercises"][0]["suggestion"]["label"] == "Subir carga"

        plan_comparison = compare_plan_to_session(sessions[1])
        assert plan_comparison["rows"][0]["target_reps_min"] == 6
        assert plan_comparison["rows"][0]["target_reps_max"] == 8
        assert plan_comparison["rows"][0]["reps_difference"] == 0

    exercise_view = client.get(f"/progress/exercises/{exercise_id}")
    assert exercise_view.status_code == 200
    assert b"Subir carga" in exercise_view.data
    assert b"180.00" in exercise_view.data

    session_view = client.get(f"/progress/sessions/{session_id}")
    assert session_view.status_code == 200
    assert b"Resumen de progreso" in session_view.data
    assert b"880.00" in session_view.data
    assert "Sí".encode() in session_view.data


def test_below_range_suggests_fatigue_review(app, client, user):
    planned_day = _create_two_sessions(app, client, user)
    client.post(
        "/training-sessions/new",
        data=_session_form(planned_day, "2026-07-15T18:00", "55", "5", "1"),
    )

    with app.app_context():
        latest = db.session.execute(
            db.select(TrainingSession).order_by(TrainingSession.performed_at.desc())
        ).scalars().first()
        suggestion = overload_suggestion(latest.exercises[0])
        assert suggestion["code"] == "review_fatigue"
        assert suggestion["label"] == "Revisar fatiga"


def test_progress_views_and_service_are_isolated(app, client, user):
    _create_two_sessions(app, client, user)
    with app.app_context():
        training_session = db.session.execute(
            db.select(TrainingSession).order_by(TrainingSession.performed_at.desc())
        ).scalars().first()
        session_id = training_session.id
        exercise_id = training_session.exercises[0].id
        second = User(username="progress-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        with pytest.raises(ValueError):
            session_progress_summary(training_session, second_id)

    client.post("/logout")
    login(client, "progress-second-user", "second-password")
    assert client.get(f"/progress/sessions/{session_id}").status_code == 404
    assert client.get(f"/progress/exercises/{exercise_id}").status_code == 404
    with app.app_context():
        assert exercise_history(second_id, "Example squat") == []
