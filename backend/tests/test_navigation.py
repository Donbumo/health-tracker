from app.extensions import db
from app.models import User
from tests.conftest import login


def test_anonymous_navigation_renders_without_user_attributes(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert b"Health Tracker" in response.data
    assert b'href="/admin/system"' not in response.data
    assert b'href="/account/export.json"' not in response.data


def test_primary_navigation_exposes_health_modules(app, client, user):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    for label, path in (
        ("Dashboard", "/dashboard"),
        ("Wellness", "/daily-balance"),
        ("Peso", "/weigh-ins"),
        ("Nutrici", "/daily-nutrition"),
        ("Alacena", "/foods"),
        ("Energ", "/daily-energy"),
        ("Entrenamiento", "/training-plans"),
        ("Sesiones", "/training-sessions"),
        ("Progreso", "/progress"),
        ("Laboratorios", "/medical/labs"),
        ("Uploads", "/uploads"),
    ):
        assert label.encode() in response.data
        assert f'href="{path}"'.encode() in response.data
    assert b'href="/admin/users"' not in response.data
    assert b'href="/admin/system"' not in response.data
    progress = client.get("/progress")
    assert progress.status_code == 200
    assert b"Registrar primera sesi" in progress.data


def test_admin_navigation_remains_role_scoped(app, client):
    with app.app_context():
        admin = User(username="navigation-admin", role="admin")
        admin.set_password("admin-password")
        db.session.add(admin)
        db.session.commit()

    login(client, "navigation-admin", "admin-password")
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Admin" in response.data
    assert b'href="/admin/users"' in response.data
    assert b'href="/admin/system"' in response.data
