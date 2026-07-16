from datetime import datetime, timezone
from pathlib import Path

from app.extensions import db
from app.models import ApiDevice, ImportRun, User
from tests.conftest import login


def _import_run(user_id: int, target: str) -> ImportRun:
    return ImportRun(
        user_id=user_id,
        target_type=target,
        source_type="qa_fixture",
        status="succeeded",
        total_count=1,
        insert_count=1,
        update_count=0,
        skip_count=0,
        conflict_count=0,
        invalid_count=0,
        payload_sha256="a" * 64,
        plan_sha256="b" * 64,
        completed_at=datetime.now(timezone.utc),
    )


def test_app_shell_has_skip_link_grouped_navigation_breadcrumbs_and_post_logout(
    client, user
):
    login(client)
    html = client.get("/dashboard").get_data(as_text=True)

    assert 'class="skip-link" href="#main-content"' in html
    assert 'class="sidebar"' in html
    assert 'class="topbar"' in html
    assert 'class="breadcrumbs" aria-label="Migas de pan"' in html
    assert 'aria-current="page">Resumen diario</a>' in html
    assert '<details class="mobile-menu">' in html
    assert '<details class="mobile-menu" open' not in html
    for group in ("Hoy", "Entrenar", "Rutinas", "Historial", "Salud y actividad", "Datos", "Cuenta", "Ayuda"):
        assert group in html
    assert html.count('action="/logout" method="post"') == 2
    assert html.count('name="csrf_token"') >= 2


def test_design_system_has_responsive_dark_and_reduced_motion_rules():
    css = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "app.css"
    ).read_text(encoding="utf-8")

    for token in ("--surface:", "--text:", "--primary:", "--radius:", "--focus:"):
        assert token in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (max-width: 900px)" in css
    assert "min-height: 44px" in css
    assert "overflow-x: hidden" not in css
    assert ".table-wrap, .table-wrapper" in css


def test_account_system_is_authenticated_safe_and_user_scoped(app, client, user):
    assert client.get("/account/system").status_code == 302
    with app.app_context():
        second = User(username="system-second", role="user")
        second.set_password("fictitious-password")
        db.session.add(second)
        db.session.flush()
        db.session.add(_import_run(user, "weigh_in_batch"))
        db.session.add(_import_run(second.id, "medical_lab"))
        db.session.commit()

    login(client)
    response = client.get("/account/system")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Estado homelab" in html
    assert "Base de datos" in html
    assert "Storage raw" in html
    assert "202607" not in html  # Tests use create_all and have no Alembic table.
    for forbidden in ("DATABASE_URL", "SECRET_KEY", "API_TOKEN", "password_hash", "C:\\", "/data/"):
        assert forbidden not in html
    assert "medical_lab" not in html


def test_api_device_ui_is_owner_only_and_revoke_is_post(app, client, user):
    with app.app_context():
        second = User(username="device-second", role="user")
        second.set_password("fictitious-password")
        db.session.add(second)
        db.session.flush()
        own = ApiDevice(
            user_id=user,
            public_device_id="11111111-1111-4111-8111-111111111111",
            name="Teléfono QA propio",
            platform="android",
        )
        other = ApiDevice(
            user_id=second.id,
            public_device_id="22222222-2222-4222-8222-222222222222",
            name="Teléfono QA ajeno",
            platform="android",
        )
        db.session.add_all([own, other])
        db.session.commit()

    login(client)
    html = client.get("/account/devices").get_data(as_text=True)
    assert "Teléfono QA propio" in html
    assert "Teléfono QA ajeno" not in html
    assert 'method="post"' in html
    assert 'name="csrf_token"' in html
    assert "refresh_token" not in html
    assert client.post(
        "/account/devices/22222222-2222-4222-8222-222222222222/revoke"
    ).status_code == 404
    assert client.post(
        "/account/devices/11111111-1111-4111-8111-111111111111/revoke"
    ).status_code == 302
    with app.app_context():
        device = db.session.execute(
            db.select(ApiDevice).where(ApiDevice.user_id == user)
        ).scalar_one()
        assert device.revoked_at is not None


def test_dashboard_operations_do_not_show_another_users_import(app, client, user):
    with app.app_context():
        second = User(username="dashboard-ops-second", role="user")
        second.set_password("fictitious-password")
        db.session.add(second)
        db.session.flush()
        db.session.add(_import_run(second.id, "medical_lab"))
        db.session.add(_import_run(user, "daily_energy"))
        db.session.commit()

    login(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Operación reciente" in html
    assert "daily_energy" in html
    assert "medical_lab" not in html
    assert "Estado del día" in html
    assert 'class="card quick-actions-card"' in html
    assert 'class="card onboarding-card compact-callout"' in html
    css = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "app.css"
    ).read_text(encoding="utf-8")
    assert ".quick-actions-card { order: 1; }" in css
    assert ".today-workout-card { order: 2; }" in css
    assert ".daily-status-card { order: 7; }" in css


def test_import_tables_use_responsive_wrappers(client, user):
    login(client)
    for path in ("/imports/standard", "/imports/files", "/imports/history"):
        response = client.get(path)
        assert response.status_code == 200
    history_template = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "templates"
        / "imports"
        / "history.html"
    ).read_text(encoding="utf-8")
    assert '<div class="table-wrap"><table>' in history_template
