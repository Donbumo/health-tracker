import csv
import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import TrainingPlan, TrainingSession, TrainingSet, UploadedFile
from app.services.validation import validate_json_document
from app.services.workout_sessions import list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _import_plan(client, user_id: int) -> None:
    payload = json.dumps(training_plan_document(user_id)).encode("utf-8")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "extended-session-plan.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def _extended_session_form(planned_day: str) -> dict[str, str]:
    return {
        "planned_day": planned_day,
        "performed_at": "2026-07-03T18:30",
        "duration_minutes": "75",
        "average_heart_rate_bpm": "142",
        "calories_burned": "456.75",
        "notes": "Fictional extended training session",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_weight_kg": "62.50",
        "exercise_0_set_0_reps": "8",
        "exercise_0_set_0_rir": "2.0",
        "exercise_0_set_0_rpe": "8.5",
        "exercise_0_set_0_rest_seconds": "120",
        "exercise_0_set_0_notes": "Fictional extended set",
    }


def test_manual_extended_session_round_trips_through_all_exports(
    app,
    client,
    user,
):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key

    response = client.post(
        "/training-sessions/new",
        data=_extended_session_form(planned_day),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Sesión registrada correctamente.".encode() in response.data
    assert b"4500 segundos" in response.data
    assert b"142 bpm" in response.data
    assert b"456.75" in response.data

    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        source_file = db.session.get(UploadedFile, session.source_file_id)
        session_id = session.id

        assert session.duration_seconds == 4500
        assert session.average_heart_rate_bpm == 142
        assert session.calories_burned == Decimal("456.75")
        assert training_set.rpe == Decimal("8.5")
        assert training_set.rest_seconds == 120

        document = json.loads(
            (app.config["DATA_ROOT"] / source_file.storage_path).read_bytes()
        )
        validate_json_document(document, "completed_workout")
        assert document["data"]["duration_seconds"] == 4500
        assert document["data"]["average_heart_rate_bpm"] == 142
        assert document["data"]["calories_burned"] == 456.75
        generated_set = document["data"]["exercises"][0]["sets"][0]
        assert generated_set["rpe"] == 8.5
        assert generated_set["rest_seconds"] == 120

    exported_json = client.get(f"/training-sessions/{session_id}/export/json")
    exported_document = json.loads(exported_json.data)
    validate_json_document(exported_document, "completed_workout")
    assert exported_document["data"]["duration_seconds"] == 4500
    assert exported_document["data"]["exercises"][0]["sets"][0]["rpe"] == 8.5

    exported_csv = client.get(f"/training-sessions/{session_id}/export/csv")
    csv_rows = list(
        csv.DictReader(io.StringIO(exported_csv.data.decode("utf-8-sig")))
    )
    assert csv_rows[0]["duration_seconds"] == "4500"
    assert csv_rows[0]["average_heart_rate_bpm"] == "142"
    assert csv_rows[0]["calories_burned"] == "456.75"
    assert csv_rows[0]["rpe"] == "8.5"
    assert csv_rows[0]["rest_seconds"] == "120"

    exported_html = client.get(f"/training-sessions/{session_id}/export/html")
    assert b"RPE" in exported_html.data
    assert "FC promedio: 142 bpm".encode() in exported_html.data
    assert b"120" in exported_html.data


def test_import_extended_completed_workout_json(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        version = plan.versions[0]
        plan_id = plan.id
        version_id = version.id

    document = {
        "schema_version": "1.0",
        "record_type": "completed_workout",
        "user_id": user,
        "source_type": "uploaded",
        "data": {
            "training_plan_id": plan_id,
            "training_plan_version_id": version_id,
            "performed_at": "2026-07-04T18:30:00+00:00",
            "planned_week_number": 1,
            "planned_day_number": 1,
            "duration_seconds": 3600,
            "average_heart_rate_bpm": 135,
            "calories_burned": 380.5,
            "notes": "Fictional imported extended session",
            "exercises": [
                {
                    "exercise_order": 1,
                    "planned_exercise_order": 1,
                    "name": "Example squat",
                    "sets": [
                        {
                            "set_number": 1,
                            "planned_set_number": 1,
                            "weight_kg": 60,
                            "reps": 8,
                            "rir": 2,
                            "rpe": 8,
                            "rest_seconds": 90,
                        }
                    ],
                }
            ],
        },
    }
    payload = json.dumps(document).encode("utf-8")
    response = client.post(
        "/training-sessions/import",
        data={"file": (io.BytesIO(payload), "extended-workout.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Sesión JSON importada correctamente.".encode() in response.data

    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        assert session.user_id == user
        assert session.duration_seconds == 3600
        assert session.average_heart_rate_bpm == 135
        assert session.calories_burned == Decimal("380.50")
        assert training_set.user_id == user
        assert training_set.rpe == Decimal("8.0")
        assert training_set.rest_seconds == 90


def test_manual_session_rejects_invalid_extended_set_values(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
    form_data = _extended_session_form(planned_day)
    form_data["exercise_0_set_0_rpe"] = "11"

    response = client.post(
        "/training-sessions/new",
        data=form_data,
        follow_redirects=True,
    )
    assert b"RPE is outside the allowed range" in response.data
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalar_one_or_none() is None
