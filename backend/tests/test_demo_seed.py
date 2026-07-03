from datetime import datetime
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    MedicalLabReport,
    MedicalLabResult,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    UploadedFile,
    User,
    WeighIn,
)
from app.services.demo_seed import DEMO_EMAIL, DEMO_PASSWORD
from tests.conftest import login


def _count(model, user_id: int) -> int:
    return len(
        db.session.execute(
            db.select(model).where(model.user_id == user_id)
        ).scalars().all()
    )


def test_demo_seed_is_fictional_complete_and_idempotent(app, client):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed", "demo"])
    second = runner.invoke(args=["seed", "demo"])

    assert first.exit_code == 0, first.output
    assert "todos los registros son ficticios" in first.output
    assert DEMO_EMAIL in first.output
    assert DEMO_PASSWORD in first.output
    assert second.exit_code == 0, second.output
    assert "Registros creados en esta ejecución: 0" in second.output

    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == DEMO_EMAIL)
        ).scalar_one()
        user_id = user.id
        assert user.username == DEMO_EMAIL
        assert user.role == "user"
        assert user.check_password(DEMO_PASSWORD)
        assert _count(WeighIn, user_id) == 2
        assert _count(DailyEnergy, user_id) == 2
        assert _count(DailyNutrition, user_id) == 2
        assert _count(TrainingPlan, user_id) == 1
        assert _count(TrainingPlanVersion, user_id) == 1
        assert _count(TrainingSession, user_id) == 1
        assert _count(TrainingSessionExercise, user_id) == 1
        assert _count(TrainingSet, user_id) == 2
        assert _count(MedicalLabReport, user_id) == 1
        assert _count(MedicalLabResult, user_id) == 7
        assert db.session.execute(db.select(UploadedFile)).scalar_one_or_none() is None

        plan = db.session.execute(
            db.select(TrainingPlan).where(TrainingPlan.user_id == user_id)
        ).scalar_one()
        assert "ficticia" in plan.name

    response = login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 302
    today = datetime.now(ZoneInfo(app.config["APP_TIMEZONE"])).date()
    dashboard = client.get("/dashboard", query_string={"date": today.isoformat()})
    assert dashboard.status_code == 200
    assert "Día completo para el balance energético".encode() in dashboard.data
    assert b"Sentadilla ficticia QA" in dashboard.data
    assert "Laboratorio ficticio QA".encode() in dashboard.data
    plans = client.get("/training-plans")
    assert plans.status_code == 200
    assert "Rutina ficticia QA".encode() in plans.data
