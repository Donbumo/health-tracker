from datetime import datetime
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    TrainingPlan,
    TrainingSession,
    WeighIn,
)
from app.services.demo_seed import DEMO_EMAIL, DEMO_PASSWORD
from tests.conftest import login


def test_authenticated_primary_web_routes_and_admin_permissions(app, client, user):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.is_json

    login(client)
    for path in (
        "/dashboard",
        "/daily-balance",
        "/daily-energy",
        "/daily-nutrition",
        "/weigh-ins",
        "/training-plans",
        "/training-sessions",
        "/progress",
        "/medical/labs",
        "/medical/markers",
        "/uploads",
        "/manual/energy",
        "/manual/nutrition",
        "/manual/weigh-in",
        "/account/export.json",
        "/account/import-preview",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
    assert client.get("/admin/users").status_code == 403
    assert client.get("/admin/system").status_code == 403

    client.post("/logout")
    seeded = app.test_cli_runner().invoke(args=["seed-admin"])
    assert seeded.exit_code == 0
    login(client, "initial-admin", "a-secure-test-password")
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/system").status_code == 200


def test_demo_smoke_exports_content_types_and_user_isolation(app, client, user):
    seeded = app.test_cli_runner().invoke(args=["seed", "demo"])
    assert seeded.exit_code == 0, seeded.output
    login(client, DEMO_EMAIL, DEMO_PASSWORD)

    today = datetime.now(ZoneInfo(app.config["APP_TIMEZONE"])).date()
    dashboard = client.get("/dashboard", query_string={"date": today.isoformat()})
    assert dashboard.status_code == 200

    with app.app_context():
        energy_id = db.session.execute(
            db.select(DailyEnergy.id).where(DailyEnergy.date == today)
        ).scalar_one()
        nutrition_id = db.session.execute(
            db.select(DailyNutrition.id).where(DailyNutrition.date == today)
        ).scalar_one()
        weigh_in_id = db.session.execute(
            db.select(WeighIn.id).order_by(WeighIn.recorded_at.desc())
        ).scalars().first()
        plan_id = db.session.execute(db.select(TrainingPlan.id)).scalar_one()
        session_id = db.session.execute(db.select(TrainingSession.id)).scalar_one()

    exports = (
        (f"/daily-energy/{energy_id}/export/json", "application/json"),
        (f"/daily-energy/{energy_id}/export/csv", "text/csv"),
        (f"/daily-nutrition/{nutrition_id}/export/json", "application/json"),
        (f"/daily-nutrition/{nutrition_id}/export/csv", "text/csv"),
        (f"/weigh-ins/{weigh_in_id}/export/json", "application/json"),
        ("/weigh-ins/export/csv", "text/csv"),
        (f"/training-plans/{plan_id}/export/json", "application/json"),
        (f"/training-plans/{plan_id}/export/csv", "text/csv"),
        (f"/training-sessions/{session_id}/export/json", "application/json"),
        (f"/training-sessions/{session_id}/export/csv", "text/csv"),
        (f"/training-sessions/{session_id}/export/html", "text/html"),
    )
    for path, content_type in exports:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.mimetype == content_type, path

    client.post("/logout")
    login(client)
    for path in (
        f"/daily-energy/{energy_id}",
        f"/daily-nutrition/{nutrition_id}",
        f"/weigh-ins/{weigh_in_id}",
        f"/training-plans/{plan_id}",
        f"/training-sessions/{session_id}",
        f"/progress/sessions/{session_id}",
    ):
        assert client.get(path).status_code == 404, path
    history_csv = client.get("/weigh-ins/export/csv")
    assert history_csv.status_code == 200
    assert b"74.500" not in history_csv.data
