from app.extensions import db
from app.models import DailyNutrition, MedicalLabReport
from app.services.demo_seed import DEMO_EMAIL, DEMO_PASSWORD
from tests.conftest import login


def test_authenticated_logout_redirects_and_protects_dashboard(app, client, user):
    assert login(client).status_code == 302

    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 302
    assert "/login" in dashboard.headers["Location"]


def test_logout_without_or_with_expired_session_never_errors(app, client, user):
    anonymous = client.post("/logout")
    assert anonymous.status_code == 302
    assert anonymous.headers["Location"] == "/login"

    login(client)
    with client.session_transaction() as session:
        session.pop("_user_id", None)
        session.pop("_fresh", None)

    expired = client.post("/logout")
    assert expired.status_code == 302
    assert expired.headers["Location"] == "/login"


def test_logout_after_rendering_admin_page(app, client):
    seeded = app.test_cli_runner().invoke(args=["seed-admin"])
    assert seeded.exit_code == 0, seeded.output
    login(client, "initial-admin", "a-secure-test-password")
    assert client.get("/admin/users").status_code == 200

    assert client.post("/logout").status_code == 302
    assert client.get("/admin/users").status_code == 302


def test_logout_after_rendering_nutrition_and_medical_details(app, client):
    seeded = app.test_cli_runner().invoke(args=["seed", "demo"])
    assert seeded.exit_code == 0, seeded.output
    login(client, DEMO_EMAIL, DEMO_PASSWORD)

    with app.app_context():
        nutrition_id = db.session.execute(
            db.select(DailyNutrition.id).order_by(DailyNutrition.date.desc())
        ).scalars().first()
        medical_id = db.session.execute(db.select(MedicalLabReport.id)).scalar_one()

    assert client.get(f"/daily-nutrition/{nutrition_id}").status_code == 200
    assert client.get(f"/medical/labs/{medical_id}").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get(f"/medical/labs/{medical_id}").status_code == 302
