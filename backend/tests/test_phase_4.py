import hashlib
import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import (
    TrainingPlan,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    UploadedFile,
    User,
)
from app.services.validation import validate_json_document
from app.services.workout_sessions import list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _import_plan(client, user_id: int) -> None:
    document = training_plan_document(user_id)
    payload = json.dumps(document).encode("utf-8")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "phase4-plan.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def _session_form(planned_day: str) -> dict[str, str]:
    return {
        "planned_day": planned_day,
        "performed_at": "2026-07-01T18:30",
        "notes": "Fictional completed session",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_weight_kg": "62.50",
        "exercise_0_set_0_reps": "6",
        "exercise_0_set_0_rir": "2.5",
        "exercise_0_set_0_notes": "Fictional set note",
    }


def test_manual_session_generates_json_imports_and_compares(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        option = list_planned_days(user)[0]
        planned_day_key = option.key
        plan_id = option.plan.id
        version_id = option.version.id

    response = client.post(
        "/training-sessions/new",
        data=_session_form(planned_day_key),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Sesión registrada correctamente.".encode() in response.data
    assert b"1/1" in response.data
    assert b"1/2" in response.data
    assert b"Omitida" in response.data
    assert b"-2" in response.data

    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        exercise = db.session.execute(
            db.select(TrainingSessionExercise)
        ).scalar_one()
        training_set = db.session.execute(db.select(TrainingSet)).scalar_one()
        source_file = db.session.get(UploadedFile, session.source_file_id)
        session_id = session.id

        assert session.user_id == user
        assert session.training_plan_id == plan_id
        assert session.training_plan_version_id == version_id
        assert session.planned_week_number == 1
        assert session.planned_day_number == 1
        assert exercise.user_id == user
        assert exercise.training_session_id == session.id
        assert training_set.user_id == user
        assert training_set.weight_kg == Decimal("62.50")
        assert training_set.reps == 6
        assert training_set.rir == Decimal("2.5")
        assert training_set.notes == "Fictional set note"
        assert source_file.source_type == "manual_generated"
        assert source_file.user_id == user

        generated_path = app.config["DATA_ROOT"] / source_file.storage_path
        generated_bytes = generated_path.read_bytes()
        assert hashlib.sha256(generated_bytes).hexdigest() == source_file.sha256
        document = json.loads(generated_bytes)
        validate_json_document(document, "completed_workout")
        assert document["user_id"] == user
        assert document["data"]["training_plan_id"] == plan_id
        assert document["data"]["training_plan_version_id"] == version_id

    listing = client.get("/training-sessions")
    assert listing.status_code == 200
    assert b"Fictional Foundation Plan" in listing.data
    assert client.get(f"/training-sessions/{session_id}").status_code == 200

    duplicate = client.post(
        "/training-sessions/new",
        data=_session_form(planned_day_key),
        follow_redirects=True,
    )
    assert "ya estaba registrada".encode() in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(TrainingSession)).scalars().all()) == 1
        assert len(db.session.execute(db.select(TrainingSet)).scalars().all()) == 1


def test_session_requires_a_completed_set(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day_key = list_planned_days(user)[0].key

    response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day_key,
            "performed_at": "2026-07-01T18:30",
        },
        follow_redirects=True,
    )
    assert b"Complete at least one training set" in response.data
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalar_one_or_none() is None


def test_sessions_are_isolated_by_user(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day_key = list_planned_days(user)[0].key
    client.post("/training-sessions/new", data=_session_form(planned_day_key))

    with app.app_context():
        session_id = db.session.execute(db.select(TrainingSession.id)).scalar_one()
        second = User(username="session-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "session-second-user", "second-password")
    assert b"Fictional Foundation Plan" not in client.get("/training-sessions").data
    assert client.get(f"/training-sessions/{session_id}").status_code == 404
    assert b"No hay d" in client.get("/training-sessions/new").data


def test_session_form_rejects_invalid_rir(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        planned_day_key = list_planned_days(user)[0].key
    form_data = _session_form(planned_day_key)
    form_data["exercise_0_set_0_rir"] = "NaN"

    response = client.post(
        "/training-sessions/new",
        data=form_data,
        follow_redirects=True,
    )
    assert b"RIR is outside the allowed range" in response.data
    with app.app_context():
        assert db.session.execute(db.select(TrainingSession)).scalar_one_or_none() is None


def test_session_keeps_historical_plan_version(app, client, user):
    login(client)
    _import_plan(client, user)
    with app.app_context():
        option = list_planned_days(user)[0]
        planned_day_key = option.key
        version_id = option.version.id
    client.post("/training-sessions/new", data=_session_form(planned_day_key))

    with app.app_context():
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        assert session.training_plan_version_id == version_id
        assert session.training_plan_id == plan.id
