from app.extensions import db
from app.models import User
from tests.conftest import login


def _seed_and_login_admin(app, client) -> None:
    result = app.test_cli_runner().invoke(args=["seed-admin"])
    assert result.exit_code == 0
    response = login(client, "initial-admin", "a-secure-test-password")
    assert response.status_code == 302


def test_admin_lists_creates_and_new_user_can_login(app, client, user):
    _seed_and_login_admin(app, client)
    listing = client.get("/admin/users")
    assert listing.status_code == 200
    assert b"initial-admin" in listing.data
    assert b"test-user" in listing.data

    response = client.post(
        "/admin/users/create",
        data={
            "email": "New.User@Example.test",
            "password": "temporary-password-123",
            "role": "user",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"new.user@example.test" in response.data

    with app.app_context():
        created = db.session.execute(
            db.select(User).where(User.email == "new.user@example.test")
        ).scalar_one()
        assert created.username == "new.user@example.test"
        assert created.role == "user"
        assert created.check_password("temporary-password-123")

    client.post("/logout")
    response = login(
        client,
        "new.user@example.test",
        "temporary-password-123",
    )
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_normal_user_cannot_list_or_create_users(app, client, user):
    login(client)
    assert client.get("/admin/users").status_code == 403
    response = client.post(
        "/admin/users/create",
        data={
            "email": "blocked@example.test",
            "password": "temporary-password-123",
            "role": "admin",
        },
    )
    assert response.status_code == 403
    with app.app_context():
        assert db.session.execute(
            db.select(User).where(User.email == "blocked@example.test")
        ).scalar_one_or_none() is None


def test_admin_rejects_duplicate_email_case_insensitively(app, client, user):
    _seed_and_login_admin(app, client)
    form_data = {
        "email": "duplicate@example.test",
        "password": "temporary-password-123",
        "role": "user",
    }
    first = client.post("/admin/users/create", data=form_data)
    assert first.status_code == 302

    duplicate = client.post(
        "/admin/users/create",
        data={**form_data, "email": "DUPLICATE@EXAMPLE.TEST"},
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert b"Ya existe un usuario con ese email." in duplicate.data
    with app.app_context():
        users = db.session.execute(
            db.select(User).where(User.email == "duplicate@example.test")
        ).scalars().all()
        assert len(users) == 1
