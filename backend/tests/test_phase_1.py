import hashlib
import io
import re

from app.extensions import db
from app.models import UploadedFile, User
from tests.conftest import login


def _csrf_token(response) -> str:
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match is not None
    return match.group(1).decode()


def test_login_logout_and_external_next_is_rejected(client, user):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    response = client.post(
        "/login?next=//example.com",
        data={"username": "test-user", "password": "test-password"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    response = client.post("/logout")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"


def test_login_and_logout_require_valid_csrf(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    token = _csrf_token(client.get("/login"))

    response = client.post(
        "/login",
        data={
            "username": "test-user",
            "password": "test-password",
            "csrf_token": token,
        },
    )
    assert response.status_code == 302

    assert client.post("/logout").status_code == 400
    home = client.get("/")
    assert home.status_code == 200

    response = client.post("/logout", data={"csrf_token": _csrf_token(home)})
    assert response.status_code == 302


def test_upload_is_hashed_stored_and_deduplicated(app, client, user):
    payload = b"fictional phase-one test data\n"
    expected_hash = hashlib.sha256(payload).hexdigest()
    login(client)

    response = client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "../../report.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Archivo guardado correctamente" in response.data

    with app.app_context():
        record = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert record.user_id == user
        assert record.original_filename == "report.txt"
        assert record.sha256 == expected_hash
        assert record.stored_filename == expected_hash
        stored_path = app.config["UPLOAD_ROOT"] / f"user_{user}" / expected_hash
        assert stored_path.read_bytes() == payload

    response = client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "copy.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"ya estaba registrado" in response.data

    with app.app_context():
        assert len(db.session.execute(db.select(UploadedFile)).scalars().all()) == 1


def test_same_hash_is_allowed_for_different_users(app, client, user):
    payload = b"same fictional bytes"
    login(client)
    client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "first.bin")},
        content_type="multipart/form-data",
    )
    client.post("/logout")

    with app.app_context():
        second = User(username="second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    login(client, "second-user", "second-password")
    response = client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "second.bin")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Archivo guardado correctamente" in response.data

    with app.app_context():
        records = db.session.execute(db.select(UploadedFile)).scalars().all()
        assert {record.user_id for record in records} == {user, second_id}
        assert (app.config["UPLOAD_ROOT"] / f"user_{user}").is_dir()
        assert (app.config["UPLOAD_ROOT"] / f"user_{second_id}").is_dir()


def test_seed_admin_is_idempotent(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed-admin"])
    second = runner.invoke(args=["seed-admin"])

    assert first.exit_code == 0
    assert "created" in first.output
    assert second.exit_code == 0
    assert "already exists" in second.output

    with app.app_context():
        admin = db.session.execute(
            db.select(User).where(User.username == "initial-admin")
        ).scalar_one()
        assert admin.role == "admin"
        assert admin.check_password("a-secure-test-password")
