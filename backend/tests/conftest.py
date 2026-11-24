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
            "DATA_ROOT": tmp_path,
            "UPLOAD_ROOT": tmp_path / "uploads" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "uploads" / "generated",
            "PORTABILITY_ROOT": tmp_path / "portability",
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


# Fictional test credential, used only with isolated QA databases.
DEMO_TEST_PASSWORD = "fictional-demo-test-password"


@pytest.fixture
def demo_enabled(app, monkeypatch):
    app.config.update(DEMO_SEED_ENABLED=True, DEMO_SEED_ENVIRONMENT="test",
                      NUTRITION_INTELLIGENCE_ENABLED=True)
    monkeypatch.setenv("DEMO_USER_PASSWORD", DEMO_TEST_PASSWORD)
    return app


@pytest.fixture
def demo_account(demo_enabled):
    result = demo_enabled.test_cli_runner().invoke(args=["seed", "demo", "--as-of", "2026-11-18", "--confirm-local"])
    assert result.exit_code == 0, result.output
    return result
