import pytest

from app import create_app
from app.extensions import db
from app.models import User


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-that-is-long-enough",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "UPLOAD_ROOT": tmp_path / "uploads" / "raw",
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
