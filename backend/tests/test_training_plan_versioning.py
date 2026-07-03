import io
import json

from app.extensions import db
from app.models import (
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    UploadedFile,
    User,
)
from app.services.training_plans import get_active_version
from app.services.workout_sessions import compare_plan_to_session, list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _upload_document(document: dict, filename: str) -> dict:
    return {
        "file": (
            io.BytesIO(json.dumps(document, ensure_ascii=False).encode("utf-8")),
            filename,
        )
    }


def _import_initial_plan(client, user_id: int) -> None:
    response = client.post(
        "/training-plans/import",
        data=_upload_document(training_plan_document(user_id), "version-v1.json"),
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def _version_two_document(user_id: int) -> dict:
    document = training_plan_document(user_id)
    document["data"]["name"] = "Fictional Foundation Plan Updated"
    document["data"]["description"] = "Fictional second version for tests."
    sets = document["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"]
    for planned_set in sets:
        planned_set["reps"] = 10
    return document


def _create_version_two(client, plan_id: int, user_id: int, follow=False):
    return client.post(
        f"/training-plans/{plan_id}/versions/new",
        data={
            **_upload_document(_version_two_document(user_id), "version-v2.json"),
            "change_reason": "Increase the target repetitions",
        },
        content_type="multipart/form-data",
        follow_redirects=follow,
    )


def _session_form(planned_day: str) -> dict[str, str]:
    return {
        "planned_day": planned_day,
        "performed_at": "2026-07-01T18:30",
        "notes": "Fictional session created with version one",
        "exercise_0_set_0_completed": "1",
        "exercise_0_set_0_weight_kg": "50",
        "exercise_0_set_0_reps": "8",
        "exercise_0_set_0_rir": "2",
    }


def test_create_history_and_activate_training_plan_version(app, client, user):
    login(client)
    _import_initial_plan(client, user)
    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        plan_id = plan.id
        version_one = db.session.execute(
            db.select(TrainingPlanVersion)
        ).scalar_one()
        version_one_id = version_one.id
        original_content = version_one.content
        assert version_one.created_by_user_id == user
        assert version_one.change_reason == "Initial import"

    response = _create_version_two(client, plan_id, user, follow=True)
    assert response.status_code == 200
    assert "Versión 2 creada; la versión activa no cambió.".encode() in response.data
    assert b"Increase the target repetitions" in response.data

    with app.app_context():
        plan = db.session.get(TrainingPlan, plan_id)
        versions = db.session.execute(
            db.select(TrainingPlanVersion).order_by(
                TrainingPlanVersion.version_number
            )
        ).scalars().all()
        assert [item.version_number for item in versions] == [1, 2]
        assert plan.active_version_number == 1
        assert versions[0].id == version_one_id
        assert versions[0].content == original_content
        assert versions[1].content["data"]["name"].endswith("Updated")
        assert versions[1].content["data"]["weeks"][0]["days"][0]["exercises"][0][
            "sets"
        ][0]["reps"] == 10
        assert versions[1].created_by_user_id == user
        assert versions[1].change_reason == "Increase the target repetitions"
        assert versions[1].source_file.user_id == user
        version_two_id = versions[1].id

    duplicate = _create_version_two(client, plan_id, user, follow=True)
    assert b"ya existe como versi" in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(TrainingPlanVersion)).scalars().all()) == 2

    activated = client.post(
        f"/training-plans/{plan_id}/versions/{version_two_id}/activate",
        follow_redirects=True,
    )
    assert activated.status_code == 200
    assert "Versión 2 activada.".encode() in activated.data
    assert activated.data.count(b"<strong>Activa</strong>") == 1

    with app.app_context():
        plan = db.session.get(TrainingPlan, plan_id)
        active = get_active_version(plan, user)
        assert plan.active_version_number == 2
        assert plan.name == "Fictional Foundation Plan Updated"
        assert plan.description == "Fictional second version for tests."
        assert active.id == version_two_id
        assert db.session.get(TrainingPlanVersion, version_one_id).content == original_content

    exported = client.get(f"/training-plans/{plan_id}/export/json")
    assert json.loads(exported.data)["data"]["name"] == (
        "Fictional Foundation Plan Updated"
    )


def test_historical_session_keeps_original_version_after_activation(
    app,
    client,
    user,
):
    login(client)
    _import_initial_plan(client, user)
    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        plan_id = plan.id
        version_one_id = get_active_version(plan, user).id
        planned_day = list_planned_days(user)[0].key

    session_response = client.post(
        "/training-sessions/new",
        data=_session_form(planned_day),
    )
    assert session_response.status_code == 302
    _create_version_two(client, plan_id, user)

    with app.app_context():
        version_two = db.session.execute(
            db.select(TrainingPlanVersion).where(
                TrainingPlanVersion.version_number == 2
            )
        ).scalar_one()
        version_two_id = version_two.id

    client.post(f"/training-plans/{plan_id}/versions/{version_two_id}/activate")

    with app.app_context():
        training_session = db.session.execute(db.select(TrainingSession)).scalar_one()
        assert training_session.training_plan_version_id == version_one_id
        comparison = compare_plan_to_session(training_session)
        assert comparison["rows"][0]["target_reps"] == 8

        active_day = list_planned_days(user)[0]
        assert active_day.version.id == version_two_id
        assert active_day.day["exercises"][0]["sets"][0]["reps"] == 10


def test_training_plan_version_routes_are_isolated(app, client, user):
    login(client)
    _import_initial_plan(client, user)
    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        plan_id = plan.id
        version_id = plan.versions[0].id
        source_count = len(db.session.execute(db.select(UploadedFile)).scalars().all())
        second = User(username="version-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "version-second-user", "second-password")
    assert client.get(f"/training-plans/{plan_id}/versions").status_code == 404
    assert client.get(f"/training-plans/{plan_id}/versions/new").status_code == 404
    assert _create_version_two(client, plan_id, user).status_code == 404
    assert (
        client.post(
            f"/training-plans/{plan_id}/versions/{version_id}/activate"
        ).status_code
        == 404
    )

    with app.app_context():
        assert len(db.session.execute(db.select(TrainingPlanVersion)).scalars().all()) == 1
        assert len(db.session.execute(db.select(UploadedFile)).scalars().all()) == source_count
