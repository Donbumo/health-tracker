from app.extensions import db
from app.models import User
from tests.conftest import login


def test_admin_system_requires_admin(app, client, user):
    assert client.get("/admin/system").status_code == 302

    login(client)
    assert client.get("/admin/system").status_code == 403


def test_admin_system_shows_safe_operational_counts(app, client, user):
    with app.app_context():
        admin = User(username="system-admin", role="admin")
        admin.set_password("system-admin-password")
        db.session.add(admin)
        db.session.commit()

    login(client, "system-admin", "system-admin-password")
    response = client.get("/admin/system")

    assert response.status_code == 200
    assert b"Diagn" in response.data
    assert b"Base de datos" in response.data
    assert b"OK" in response.data
    assert b"Usuarios" in response.data
    assert b"Reportes m" in response.data
    assert b"password_hash" not in response.data
    assert b"test-user" not in response.data
