import csv
import hashlib
import io
import json

import pytest

from app.extensions import db
from app.models import TrainingPlan, TrainingSession, UploadedFile, User
from app.services.exporters import BaseExporter, ExportError
from app.services.exporters.training_plan import (
    TrainingPlanCsvExporter,
    TrainingPlanJsonExporter,
)
from app.services.exporters.training_session import (
    TrainingSessionCsvExporter,
    TrainingSessionHtmlExporter,
    TrainingSessionJsonExporter,
)
from app.services.validation import validate_json_document
from app.services.workout_sessions import list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _setup_plan_and_session(app, client, user) -> tuple[int, int]:
    login(client)
    plan_document = training_plan_document(user)
    client.post(
        "/training-plans/import",
        data={
            "file": (
                io.BytesIO(json.dumps(plan_document).encode("utf-8")),
                "phase6-plan.json",
            )
        },
        content_type="multipart/form-data",
    )
    with app.app_context():
        planned_day = list_planned_days(user)[0].key
        plan_id = db.session.execute(db.select(TrainingPlan.id)).scalar_one()

    response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "performed_at": "2026-07-01T18:30",
            "notes": "Fictional Phase 6 session",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_weight_kg": "62.50",
            "exercise_0_set_0_reps": "8",
            "exercise_0_set_0_rir": "2.0",
            "exercise_0_set_0_notes": "Fictional export set",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        session_id = db.session.execute(db.select(TrainingSession.id)).scalar_one()
    return plan_id, session_id


def test_exporter_services_emit_supported_formats(app, client, user):
    _setup_plan_and_session(app, client, user)

    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        session = db.session.execute(db.select(TrainingSession)).scalar_one()

        plan_json_exporter = TrainingPlanJsonExporter()
        assert isinstance(plan_json_exporter, BaseExporter)
        plan_json = plan_json_exporter.export(plan, user)
        assert json.loads(plan_json.content) == training_plan_document(user)
        assert plan_json.warning is None

        plan_csv = TrainingPlanCsvExporter().export(plan, user)
        plan_rows = list(
            csv.DictReader(io.StringIO(plan_csv.content.decode("utf-8-sig")))
        )
        assert len(plan_rows) == 3
        assert plan_rows[0]["exercise_name"] == "Example squat"
        assert plan_rows[0]["reps"] == "8"
        assert plan_rows[2]["day_name"] == "Rest day"
        assert plan_csv.warning is not None

        session_json = TrainingSessionJsonExporter().export(session, user)
        session_document = json.loads(session_json.content)
        validate_json_document(session_document, "completed_workout")
        assert session_document["data"]["exercises"][0]["sets"][0]["reps"] == 8

        session_csv = TrainingSessionCsvExporter().export(session, user)
        session_rows = list(
            csv.DictReader(io.StringIO(session_csv.content.decode("utf-8-sig")))
        )
        assert len(session_rows) == 1
        assert session_rows[0]["weight_kg"] == "62.50"
        assert session_rows[0]["exercise_name"] == "Example squat"

        session_html = TrainingSessionHtmlExporter().export(session, user)
        assert session_html.inline is True
        assert b"window.print()" in session_html.content
        assert b"Example squat" in session_html.content

        second = User(username="export-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        with pytest.raises(ExportError):
            TrainingPlanJsonExporter().export(plan, second.id)
        with pytest.raises(ExportError):
            TrainingSessionCsvExporter().export(session, second.id)


def test_export_http_routes_and_user_isolation(app, client, user):
    plan_id, session_id = _setup_plan_and_session(app, client, user)

    plan_json = client.get(f"/training-plans/{plan_id}/export/json")
    assert plan_json.status_code == 200
    assert plan_json.mimetype == "application/json"
    assert "attachment" in plan_json.headers["Content-Disposition"]

    plan_csv = client.get(f"/training-plans/{plan_id}/export/csv")
    assert plan_csv.status_code == 200
    assert plan_csv.mimetype == "text/csv"
    assert b"exercise_name" in plan_csv.data

    session_json = client.get(f"/training-sessions/{session_id}/export/json")
    assert session_json.status_code == 200
    assert session_json.mimetype == "application/json"
    validate_json_document(json.loads(session_json.data), "completed_workout")

    session_csv = client.get(f"/training-sessions/{session_id}/export/csv")
    assert session_csv.status_code == 200
    assert session_csv.mimetype == "text/csv"
    assert b"planned_set_number" in session_csv.data

    session_html = client.get(f"/training-sessions/{session_id}/export/html")
    assert session_html.status_code == 200
    assert session_html.mimetype == "text/html"
    assert "inline" in session_html.headers["Content-Disposition"]
    assert client.get(f"/training-sessions/{session_id}/export/pdf").status_code == 404

    with app.app_context():
        second = User(username="http-export-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "http-export-second-user", "second-password")
    assert client.get(f"/training-plans/{plan_id}/export/json").status_code == 404
    assert client.get(f"/training-plans/{plan_id}/export/csv").status_code == 404
    assert client.get(f"/training-sessions/{session_id}/export/json").status_code == 404
    assert client.get(f"/training-sessions/{session_id}/export/csv").status_code == 404


def test_completed_workout_json_import_preserves_source_and_deduplicates(
    app,
    client,
    user,
):
    _plan_id, original_session_id = _setup_plan_and_session(app, client, user)
    with app.app_context():
        original_session = db.session.get(TrainingSession, original_session_id)
        artifact = TrainingSessionJsonExporter().export(original_session, user)
        document = json.loads(artifact.content)
    document["source_type"] = "uploaded"
    document["data"]["performed_at"] = "2026-07-02T18:30:00+00:00"
    payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
    expected_sha = hashlib.sha256(payload).hexdigest()

    response = client.post(
        "/training-sessions/import",
        data={"file": (io.BytesIO(payload), "imported-workout.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Sesión JSON importada correctamente".encode() in response.data

    with app.app_context():
        sessions = db.session.execute(
            db.select(TrainingSession).order_by(TrainingSession.id)
        ).scalars().all()
        assert len(sessions) == 2
        imported = sessions[1]
        assert imported.user_id == user
        assert imported.training_plan_id == sessions[0].training_plan_id
        source = db.session.get(UploadedFile, imported.source_file_id)
        assert source.source_type == "uploaded"
        assert source.detected_type == "completed_workout"
        assert source.import_status == "imported"
        assert source.sha256 == expected_sha
        assert (app.config["DATA_ROOT"] / source.storage_path).read_bytes() == payload

    duplicate = client.post(
        "/training-sessions/import",
        data={"file": (io.BytesIO(payload), "same-workout.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "ya había sido importada".encode() in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(TrainingSession)).scalars().all()) == 2
        source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.sha256 == expected_sha)
        ).scalar_one()
        assert source.import_status == "duplicate"

        second = User(username="import-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    client.post("/logout")
    login(client, "import-second-user", "second-password")
    rejected = client.post(
        "/training-sessions/import",
        data={"file": (io.BytesIO(payload), "foreign-workout.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"does not belong to this user" in rejected.data
    with app.app_context():
        assert (
            db.session.execute(
                db.select(TrainingSession).where(TrainingSession.user_id == second_id)
            ).scalar_one_or_none()
            is None
        )
        second_source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == second_id)
        ).scalar_one()
        assert second_source.sha256 == expected_sha
        assert (app.config["DATA_ROOT"] / second_source.storage_path).read_bytes() == payload
