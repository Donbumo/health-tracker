import json
from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import DailyEnergy, User
from app.services.demo_seed import DEMO_EMAIL, DEMO_PASSWORD
from app.services.exporters import ExportError
from app.services.exporters.user_data import UserDataJsonExporter
from app.services.validation import validate_json_document
from tests.conftest import login


def test_account_export_requires_login(client):
    response = client.get("/account/export.json")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_account_export_contains_all_demo_sections_without_sensitive_fields(app, client):
    seeded = app.test_cli_runner().invoke(args=["seed", "demo"])
    assert seeded.exit_code == 0, seeded.output
    login(client, DEMO_EMAIL, DEMO_PASSWORD)

    response = client.get("/account/export.json")
    document = response.get_json()

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "attachment" in response.headers["Content-Disposition"]
    assert document["schema_version"] == "1.0"
    assert document["type"] == "user_data_export"
    assert document["user"]["email"] == DEMO_EMAIL
    assert document["user"]["role"] == "user"
    assert set(document["data"]) == {
        "weigh_ins",
        "daily_nutrition",
        "daily_energy",
        "daily_balances",
        "training_plans",
        "training_sessions",
        "medical_lab_reports",
        "uploads",
        "food_products",
        "recipes",
            "activities",
            "routes",
            "export_records",
        }
    assert len(document["data"]["weigh_ins"]) == 2
    assert len(document["data"]["daily_nutrition"]) == 2
    assert len(document["data"]["daily_energy"]) == 2
    assert len(document["data"]["training_plans"][0]["versions"]) == 1
    assert len(document["data"]["training_sessions"]) == 1
    assert len(document["data"]["medical_lab_reports"]) == 1
    with app.app_context():
        validate_json_document(document, "user_data_export")

    serialized = json.dumps(document)
    for forbidden in (
        "password_hash",
        "stored_filename",
        "storage_path",
        "error_message",
        "a-secure-test-password",
    ):
        assert forbidden not in serialized


def test_account_export_is_strictly_isolated_by_user(app, client, user):
    with app.app_context():
        owner = db.session.get(User, user)
        owner.email = "owner@example.test"
        second = User(
            username="export-private-user",
            email="private@example.test",
            role="user",
        )
        second.set_password("private-user-password")
        db.session.add(second)
        db.session.flush()
        db.session.add_all(
            [
                DailyEnergy(
                    user_id=owner.id,
                    date=date(2026, 7, 1),
                    total_calories=Decimal("2100"),
                    source="owner-only-source",
                ),
                DailyEnergy(
                    user_id=second.id,
                    date=date(2026, 7, 2),
                    total_calories=Decimal("9999"),
                    source="private-user-source",
                ),
            ]
        )
        db.session.commit()
        second_id = second.id

        with pytest.raises(ExportError):
            UserDataJsonExporter().export(second, owner.id)

    login(client)
    response = client.get("/account/export.json")
    document = response.get_json()
    serialized = json.dumps(document)

    assert response.status_code == 200
    assert document["user"] == {
        "id": user,
        "email": "owner@example.test",
        "role": "user",
    }
    assert "owner-only-source" in serialized
    assert "private-user-source" not in serialized
    assert "private@example.test" not in serialized
    assert str(second_id) not in json.dumps(document["user"])
