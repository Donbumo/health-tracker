from datetime import date, datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import (
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
)
from app.services.daily_dashboard import daily_health_dashboard
from tests.conftest import login


TARGET_DATE = "2026-07-09"


def test_empty_dashboard_exposes_daily_driver_quick_actions(client, user):
    login(client)
    response = client.get("/dashboard", query_string={"date": TARGET_DATE})
    assert response.status_code == 200
    for label, path in (
        ("Nutrición", "/manual/nutrition"),
        ("Energía", "/manual/energy"),
        ("Peso", "/manual/weigh-in"),
        ("Registrar entrenamiento", "/training-sessions/new"),
        ("Importar", "/imports"),
        ("Ver progreso", "/progress"),
    ):
        assert label.encode() in response.data
        assert f'href="{path}"'.encode() in response.data


def _create_wellness_day(client):
    client.post(
        "/manual/energy",
        data={
            "date": TARGET_DATE,
            "total_calories": "2300",
            "active_calories": "500",
            "steps": "7500",
        },
    )
    client.post(
        "/manual/nutrition",
        data={
            "date": TARGET_DATE,
            "meal_type": "dinner",
            "item_name": "Fictional dashboard item",
            "calories": "650",
            "protein_g": "45",
            "fat_g": "20",
            "net_carbs_g": "55",
            "fiber_g": "8",
        },
    )
    client.post(
        "/manual/weigh-in",
        data={
            "recorded_at": f"{TARGET_DATE}T07:00",
            "weight_kg": "72.6",
            "body_fat_percent": "17.5",
            "muscle_mass_kg": "57.9",
        },
    )


def _create_training_session(user_id: int, performed_at: datetime) -> int:
    content = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Fictional dashboard plan",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Dashboard day",
                            "exercises": [],
                        }
                    ],
                }
            ],
        },
    }
    plan = TrainingPlan(
        user_id=user_id,
        name="Fictional dashboard plan",
        active_version_number=1,
    )
    db.session.add(plan)
    db.session.flush()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan_id=plan.id,
        version_number=1,
        created_by_user_id=user_id,
        schema_version="1.0",
        sha256=f"{user_id:064x}",
        content=content,
    )
    db.session.add(version)
    db.session.flush()
    training_session = TrainingSession(
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        performed_at=performed_at,
        planned_week_number=1,
        planned_day_number=1,
        duration_seconds=3600,
        calories_burned=Decimal("320"),
    )
    db.session.add(training_session)
    db.session.flush()
    exercise = TrainingSessionExercise(
        user_id=user_id,
        training_session_id=training_session.id,
        exercise_order=1,
        planned_exercise_order=1,
        name="Fictional dashboard lift",
    )
    db.session.add(exercise)
    db.session.flush()
    for set_number in (1, 2):
        db.session.add(
            TrainingSet(
                user_id=user_id,
                training_session_exercise_id=exercise.id,
                set_number=set_number,
                planned_set_number=set_number,
                weight_kg=Decimal("50"),
                reps=8,
            )
        )
    db.session.commit()
    return training_session.id


def test_daily_dashboard_combines_wellness_weight_and_training(
    app,
    client,
    user,
):
    login(client)
    client.post(
        "/manual/weigh-in",
        data={"recorded_at": "2026-07-08T07:00", "weight_kg": "72.9"},
    )
    _create_wellness_day(client)
    with app.app_context():
        first_session_id = _create_training_session(
            user,
            datetime(2026, 7, 9, 18, tzinfo=timezone.utc),
        )
        second_session_id = _create_training_session(
            user,
            datetime(2026, 7, 9, 20, tzinfo=timezone.utc),
        )
        summary = daily_health_dashboard(user, date(2026, 7, 9), "UTC")
        assert summary["calories_consumed"] == Decimal("650.000")
        assert summary["calories_expended"] == Decimal("2300.00")
        assert summary["balance"] == Decimal("-1650.000")
        assert summary["balance_state"] == "deficit"
        assert summary["weigh_in"].weight_kg == Decimal("72.600")
        assert summary["weigh_in_is_exact_date"] is True
        assert summary["weight_change"] == Decimal("-0.300")
        assert [item["record"].id for item in summary["sessions"]] == [
            first_session_id,
            second_session_id,
        ]
        assert summary["sessions"][0]["volume"] == Decimal("800.00")
        assert summary["sessions"][0]["exercise_names"] == [
            "Fictional dashboard lift"
        ]
        assert summary["training_totals"] == {
            "session_count": 2,
            "duration_seconds": 7200,
            "volume": Decimal("1600.00"),
            "exercise_count": 2,
            "calories_burned": Decimal("640.00"),
        }
        assert summary["completion"] == {
            "status": "complete",
            "completed_count": 2,
            "required_count": 2,
            "nutrition_state": "complete",
            "energy_state": "complete",
            "weight_state": "today",
            "training_state": "recorded",
        }

    response = client.get("/dashboard", query_string={"date": TARGET_DATE})
    assert response.status_code == 200
    assert b"650.000" in response.data
    assert b"2300.00" in response.data
    assert b"-1650.000" in response.data
    assert b"72.600 kg" in response.data
    assert b"1600.00" in response.data
    assert b"Fictional dashboard lift" in response.data
    assert "Día completo para el balance energético".encode() in response.data
    assert b"-0.300 kg" in response.data
    assert b"no se suman al gasto diario" in response.data


def test_daily_dashboard_handles_missing_data_and_uses_previous_weight(
    app,
    client,
    user,
):
    login(client)
    client.post(
        "/manual/weigh-in",
        data={"recorded_at": "2026-07-08T07:00", "weight_kg": "71.9"},
    )
    response = client.get("/dashboard", query_string={"date": TARGET_DATE})
    assert response.status_code == 200
    assert b"Nutrici" in response.data and b"pendiente" in response.data
    assert b"Energ" in response.data and b"pendiente" in response.data
    assert b"71.900 kg" in response.data
    assert b"ltimo registro anterior" in response.data
    assert b"No hay sesi" in response.data
    with app.app_context():
        summary = daily_health_dashboard(user, date(2026, 7, 9), "UTC")
        assert summary["completion"]["status"] == "empty"
        assert summary["completion"]["weight_state"] == "carried_forward"
        assert summary["completion"]["training_state"] == "none"


def test_daily_dashboard_distinguishes_partial_records_from_missing_data(
    app,
    client,
    user,
):
    login(client)
    client.post(
        "/manual/energy",
        data={"date": TARGET_DATE, "active_calories": "420"},
    )
    client.post(
        "/manual/nutrition",
        data={
            "date": TARGET_DATE,
            "meal_type": "breakfast",
            "item_name": "Fictional partial item",
            "protein_g": "25",
        },
    )

    with app.app_context():
        summary = daily_health_dashboard(user, date(2026, 7, 9), "UTC")
        assert summary["balance"] is None
        assert summary["balance_state"] == "incomplete"
        assert summary["completion"]["status"] == "partial"
        assert summary["completion"]["completed_count"] == 0
        assert summary["completion"]["nutrition_state"] == "partial"
        assert summary["completion"]["energy_state"] == "partial"
        assert summary["completion"]["training_state"] == "none"

    response = client.get("/dashboard", query_string={"date": TARGET_DATE})
    assert response.status_code == 200
    assert b"0/2 datos esenciales completos" in response.data
    assert b"parcial, falta el total de calor" in response.data
    assert b"parcial, falta el gasto total" in response.data
    assert b"puede ser un d" in response.data


def test_daily_dashboard_is_isolated_by_user(app, client, user):
    login(client)
    _create_wellness_day(client)
    with app.app_context():
        _create_training_session(
            user,
            datetime(2026, 7, 9, 18, tzinfo=timezone.utc),
        )
        second = User(username="dashboard-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        summary = daily_health_dashboard(second_id, date(2026, 7, 9), "UTC")
        assert summary["nutrition"] is None
        assert summary["energy"] is None
        assert summary["weigh_in"] is None
        assert summary["sessions"] == []
        assert summary["completion"]["status"] == "empty"

    client.post("/logout")
    login(client, "dashboard-second", "second-password")
    response = client.get("/dashboard", query_string={"date": TARGET_DATE})
    assert response.status_code == 200
    assert b"Fictional dashboard item" not in response.data
    assert b"Fictional dashboard lift" not in response.data
    assert b"72.600 kg" not in response.data
