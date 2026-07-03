import io
import json

import pytest

from app.extensions import db
from app.models import TrainingPlan, TrainingSessionExercise, User
from app.services.exercise_identity import (
    ExerciseIdentityError,
    add_exercise_alias,
    find_exercise_identity,
)
from app.services.overload import exercise_history
from app.services.workout_sessions import list_planned_days
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def _create_named_session(
    app,
    client,
    user_id: int,
    *,
    plan_name: str,
    exercise_name: str,
    performed_at: str,
) -> int:
    document = training_plan_document(user_id)
    document["data"]["name"] = plan_name
    document["data"]["weeks"][0]["days"][0]["exercises"][0][
        "name"
    ] = exercise_name
    response = client.post(
        "/training-plans/import",
        data={
            "file": (
                io.BytesIO(json.dumps(document).encode("utf-8")),
                f"{plan_name.casefold().replace(' ', '-')}.json",
            )
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        plan = db.session.execute(
            db.select(TrainingPlan).where(
                TrainingPlan.user_id == user_id,
                TrainingPlan.name == plan_name,
            )
        ).scalar_one()
        planned_day = list_planned_days(user_id, plan_id=plan.id)[0].key

    response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day,
            "performed_at": performed_at,
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_weight_kg": "50",
            "exercise_0_set_0_reps": "8",
            "exercise_0_set_0_rir": "2",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        return db.session.execute(
            db.select(TrainingSessionExercise.id)
            .where(
                TrainingSessionExercise.user_id == user_id,
                TrainingSessionExercise.name == exercise_name,
            )
            .order_by(TrainingSessionExercise.id.desc())
        ).scalar_one()


def test_aliases_group_historical_names_without_rewriting_them(app, client, user):
    login(client)
    canonical_exercise_id = _create_named_session(
        app,
        client,
        user,
        plan_name="Fictional T Row Plan",
        exercise_name="Remo en T",
        performed_at="2026-07-01T18:00",
    )
    _create_named_session(
        app,
        client,
        user,
        plan_name="Fictional T Bar Plan",
        exercise_name="T-bar row",
        performed_at="2026-07-08T18:00",
    )
    _create_named_session(
        app,
        client,
        user,
        plan_name="Fictional Bench Plan",
        exercise_name="Press banca",
        performed_at="2026-07-15T18:00",
    )

    with app.app_context():
        assert len(exercise_history(user, "  REMO EN T  ")) == 1
        assert len(exercise_history(user, "T-bar row")) == 1

    response = client.post(
        f"/progress/exercises/{canonical_exercise_id}/aliases",
        data={"alias_name": "T-bar row"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Alias agregado correctamente." in response.data
    assert b"T-bar row" in response.data

    with app.app_context():
        canonical_history = exercise_history(user, "Remo en T")
        alias_history = exercise_history(user, "t-BAR ROW")
        assert len(canonical_history) == 2
        assert len(alias_history) == 2
        assert [
            item["exercise"].name for item in canonical_history
        ] == ["Remo en T", "T-bar row"]
        assert len(exercise_history(user, "Press banca")) == 1


def test_private_aliases_are_isolated_by_user(app, client, user):
    login(client)
    exercise_id = _create_named_session(
        app,
        client,
        user,
        plan_name="Fictional Private Alias Plan",
        exercise_name="Remo en T pecho apoyado",
        performed_at="2026-07-01T18:00",
    )
    client.post(
        f"/progress/exercises/{exercise_id}/aliases",
        data={"alias_name": "Chest-supported T-bar row"},
    )

    with app.app_context():
        identity = find_exercise_identity(user, "Chest-supported T-bar row")
        assert identity is not None
        second = User(username="alias-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

        assert find_exercise_identity(second_id, "Chest-supported T-bar row") is None
        assert exercise_history(second_id, "Remo en T pecho apoyado") == []
        with pytest.raises(ExerciseIdentityError):
            add_exercise_alias(second_id, identity.id, "Private alias")

    client.post("/logout")
    login(client, "alias-second-user", "second-password")
    response = client.post(
        f"/progress/exercises/{exercise_id}/aliases",
        data={"alias_name": "Unauthorized alias"},
    )
    assert response.status_code == 404
