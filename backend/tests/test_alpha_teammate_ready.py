import hashlib
import json

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, User, WeighIn
from tests.conftest import login


def _seed_and_login_admin(app, client) -> None:
    result = app.test_cli_runner().invoke(args=["seed-admin"])
    assert result.exit_code == 0
    response = login(client, "initial-admin", "a-secure-test-password")
    assert response.status_code == 302


def _create_training_plan(user_id: int) -> TrainingPlanVersion:
    content = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "name": "Alpha QA plan",
            "description": "Rutina ficticia para QA alpha.",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Día ficticio",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Press ficticio",
                                    "sets": [
                                        {
                                            "set_number": 1,
                                            "reps": 8,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan = TrainingPlan(
        user_id=user_id,
        name=content["data"]["name"],
        description=content["data"]["description"],
        active_version_number=1,
    )
    db.session.add(plan)
    db.session.flush()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan_id=plan.id,
        version_number=1,
        created_by_user_id=user_id,
        change_reason="QA alpha ficticia.",
        schema_version="1.0",
        sha256=hashlib.sha256(encoded).hexdigest(),
        content=content,
    )
    db.session.add(version)
    db.session.commit()
    return version


def test_alpha_teammate_full_web_flow_and_isolation(app, client):
    _seed_and_login_admin(app, client)
    created = client.post(
        "/admin/users/create",
        data={
            "email": "teammate@example.test",
            "password": "temporary-alpha-password",
            "role": "user",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert b"teammate@example.test" in created.data

    client.post("/logout")
    assert login(client, "teammate@example.test", "temporary-alpha-password").status_code == 302

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Primeros pasos".encode() in dashboard.data
    assert b"Alpha 0.5" in dashboard.data

    weight = client.post(
        "/manual/weigh-in",
        data={
            "recorded_at": "2026-07-10T07:00",
            "weight_kg": "82.40",
        },
        follow_redirects=True,
    )
    assert weight.status_code == 200

    energy = client.post(
        "/manual/energy",
        data={
            "date": "2026-07-10",
            "total_calories": "2400",
            "active_calories": "500",
            "steps": "8000",
        },
        follow_redirects=True,
    )
    assert energy.status_code == 200

    nutrition = client.post(
        "/manual/nutrition",
        data={
            "date": "2026-07-10",
            "meal_type": "breakfast",
            "meal_name": "Desayuno ficticio",
            "item_name": "Item ficticio",
            "food_product_id": "0",
            "recipe_id": "0",
            "quantity": "1",
            "unit": "serving",
            "calories": "450",
            "protein_g": "30",
            "fat_g": "12",
            "net_carbs_g": "40",
        },
        follow_redirects=True,
    )
    assert nutrition.status_code == 200

    with app.app_context():
        teammate = db.session.execute(
            db.select(User).where(User.email == "teammate@example.test")
        ).scalar_one()
        version = _create_training_plan(teammate.id)
        planned_day_key = f"{version.id}:0:0"

    session_response = client.post(
        "/training-sessions/new",
        data={
            "planned_day": planned_day_key,
            "performed_at": "2026-07-10T18:00",
            "duration_minutes": "45",
            "average_heart_rate_bpm": "120",
            "calories_burned": "220",
            "exercise_0_set_0_completed": "1",
            "exercise_0_set_0_weight_kg": "50",
            "exercise_0_set_0_reps": "8",
            "exercise_0_set_0_rir": "2",
            "exercise_0_set_0_rpe": "8",
            "exercise_0_set_0_rest_seconds": "90",
        },
        follow_redirects=True,
    )
    assert session_response.status_code == 200

    dashboard = client.get("/dashboard", query_string={"date": "2026-07-10"})
    assert dashboard.status_code == 200
    assert b"82.400" in dashboard.data
    assert b"2400" in dashboard.data
    assert b"450" in dashboard.data
    assert "Press ficticio".encode() in dashboard.data

    export = client.get("/account/export.json")
    assert export.status_code == 200
    payload = export.get_json()
    serialized = json.dumps(payload)
    assert payload["type"] == "user_data_export"
    assert "password_hash" not in serialized
    assert payload["user"]["email"] == "teammate@example.test"
    assert payload["data"]["weigh_ins"]

    history = client.get("/imports/history")
    assert history.status_code == 200

    client.post("/logout")
    assert client.get("/dashboard").status_code == 302

    with app.app_context():
        first_weight_id = db.session.execute(db.select(WeighIn.id)).scalar_one()
        second = User(username="other@example.test", email="other@example.test", role="user")
        second.set_password("temporary-alpha-password")
        db.session.add(second)
        db.session.commit()

    assert login(client, "other@example.test", "temporary-alpha-password").status_code == 302
    assert client.get(f"/weigh-ins/{first_weight_id}").status_code == 404
    other_export = client.get("/account/export.json").get_json()
    assert other_export["data"]["weigh_ins"] == []


def test_alpha_smoke_routes(app, client, user):
    assert client.get("/healthz").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/privacy").status_code == 200

    login(client)
    for path in (
        "/",
        "/dashboard",
        "/account/export.json",
        "/imports/standard",
        "/imports/history",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
