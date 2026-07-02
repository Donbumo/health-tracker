import pytest
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import User


def _schema_root() -> Path:
    candidates = (
        Path(__file__).resolve().parents[2] / "schemas",
        Path(__file__).resolve().parents[1] / "schemas",
    )
    return next(candidate for candidate in candidates if candidate.is_dir())


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-that-is-long-enough",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "UPLOAD_ROOT": tmp_path / "uploads" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "uploads" / "generated",
            "SCHEMA_ROOT": _schema_root(),
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "ADMIN_USERNAME": "initial-admin",
            "ADMIN_PASSWORD": "a-secure-test-password",
        }
    )

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user(app):
    with app.app_context():
        account = User(username="test-user", role="user")
        account.set_password("test-password")
        db.session.add(account)
        db.session.commit()
        return account.id


def login(client, username="test-user", password="test-password"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
