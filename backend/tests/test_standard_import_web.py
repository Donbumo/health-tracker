import io
import json
import re
from html import unescape

from app.extensions import db
from app.models import DailyEnergy, User
from tests.conftest import login


def _energy_payload():
    return {
        "energia": [
            {
                "fecha": "2026-07-25",
                "calorias_totales": 2400,
            }
        ]
    }


def _hidden(response, name: str) -> str:
    match = re.search(
        rb'name="' + name.encode() + rb'"\s+type="hidden"\s+value="([^"]*)"',
        response.data,
    )
    if match is None:
        match = re.search(
            rb'type="hidden"\s+[^>]*name="' + name.encode() + rb'"[^>]*value="([^"]*)"',
            response.data,
        )
    assert match is not None, response.data.decode("utf-8", errors="replace")
    return unescape(match.group(1).decode("utf-8"))


def _csrf_token(response) -> str:
    return _hidden(response, "csrf_token")


def _preview(client, payload: dict, target_type: str = "daily_energy"):
    payload_json = json.dumps(payload)
    return client.post(
        "/imports/standard",
        data={
            "target_type": target_type,
            "file": (io.BytesIO(payload_json.encode("utf-8")), "payload.json"),
        },
        content_type="multipart/form-data",
    )


def _confirm_data(preview_response):
    data = {
        "payload_json": _hidden(preview_response, "payload_json"),
        "target_type": _hidden(preview_response, "target_type"),
        "confirmation_token": _hidden(preview_response, "confirmation_token"),
    }
    try:
        data["csrf_token"] = _csrf_token(preview_response)
    except AssertionError:
        pass
    return data


def _login_with_csrf(client, username: str, password: str):
    login_page = client.get("/login")
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf_token(login_page),
        },
    )


def _preview_with_csrf(client, payload: dict, target_type: str = "daily_energy"):
    import_page = client.get("/imports/standard")
    payload_json = json.dumps(payload)
    return client.post(
        "/imports/standard",
        data={
            "csrf_token": _csrf_token(import_page),
            "target_type": target_type,
            "file": (io.BytesIO(payload_json.encode("utf-8")), "payload.json"),
        },
        content_type="multipart/form-data",
    )


def test_standard_import_requires_login(client):
    response = client.get("/imports/standard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_standard_import_preview_is_read_only(app, client, user):
    login(client)
    response = _preview(client, _energy_payload())

    assert response.status_code == 200
    assert b"Preview" in response.data
    assert b"Confirmar" in response.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalars().all() == []


def test_standard_import_confirmation_persists_for_current_user(app, client, user):
    login(client)
    preview = _preview(client, _energy_payload())
    assert preview.status_code == 200

    response = client.post(
        "/imports/standard",
        data=_confirm_data(preview),
    )

    assert response.status_code == 200
    assert b"Resumen final" in response.data
    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert record.user_id == user
        assert record.date.isoformat() == "2026-07-25"


def test_standard_import_rejects_direct_confirmation_without_token(app, client, user):
    login(client)
    response = client.post(
        "/imports/standard",
        data={
            "payload_json": json.dumps(_energy_payload()),
            "target_type": "daily_energy",
        },
    )

    assert response.status_code == 200
    assert b"confirm" in response.data.lower()
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_rejects_tampered_payload(app, client, user):
    login(client)
    preview = _preview(client, _energy_payload())
    data = _confirm_data(preview)
    tampered = _energy_payload()
    tampered["energia"][0]["fecha"] = "2026-07-26"
    data["payload_json"] = json.dumps(tampered)

    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"Preview" in response.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_rejects_tampered_target(app, client, user):
    login(client)
    preview = _preview(client, _energy_payload())
    data = _confirm_data(preview)
    data["target_type"] = "food_products"

    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"No fue posible" in response.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_rejects_token_from_other_user(app, client, user):
    login(client)
    preview = _preview(client, _energy_payload())
    data = _confirm_data(preview)
    with app.app_context():
        second = User(username="token-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "token-second-user", "second-password")
    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"No fue posible" in response.data
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_rejects_stale_confirmation_plan(app, client, user):
    login(client)
    preview = _preview(client, _energy_payload())
    data = _confirm_data(preview)

    with app.app_context():
        from app.services.importers.standard_import_executor import StandardImportExecutor

        StandardImportExecutor().commit_documents(
            [_energy_payload_to_standard(user)],
            user_id=user,
            target_type="daily_energy",
            confirmed=True,
        )

    response = client.post("/imports/standard", data=data)

    assert response.status_code == 200
    assert b"changed" in response.data
    with app.app_context():
        records = db.session.execute(db.select(DailyEnergy)).scalars().all()
        assert len(records) == 1
        assert records[0].date.isoformat() == "2026-07-25"


def test_standard_import_confirm_requires_csrf_when_enabled(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    _login_with_csrf(client, "test-user", "test-password")
    preview = _preview_with_csrf(client, _energy_payload())
    data = _confirm_data(preview)
    data.pop("csrf_token", None)

    response = client.post("/imports/standard", data=data)

    assert response.status_code == 400
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_confirm_rejects_invalid_csrf_when_enabled(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    _login_with_csrf(client, "test-user", "test-password")
    preview = _preview_with_csrf(client, _energy_payload())
    data = _confirm_data(preview)
    data["csrf_token"] = "invalid-csrf-token"

    response = client.post("/imports/standard", data=data)

    assert response.status_code == 400
    with app.app_context():
        assert db.session.execute(db.select(DailyEnergy)).scalar_one_or_none() is None


def test_standard_import_confirm_with_valid_csrf_persists(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    _login_with_csrf(client, "test-user", "test-password")
    preview = _preview_with_csrf(client, _energy_payload())

    response = client.post("/imports/standard", data=_confirm_data(preview))

    assert response.status_code == 200
    assert b"Resumen final" in response.data
    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert record.user_id == user


def test_new_admin_created_user_can_confirm_import_into_own_account(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    result = app.test_cli_runner().invoke(args=["seed-admin"])
    assert result.exit_code == 0

    _login_with_csrf(client, "initial-admin", "a-secure-test-password")
    users_page = client.get("/admin/users")
    create_response = client.post(
        "/admin/users/create",
        data={
            "csrf_token": _csrf_token(users_page),
            "email": "qa.import@example.test",
            "password": "temporary-password-123",
            "role": "user",
        },
    )
    assert create_response.status_code == 302
    client.post("/logout", data={"csrf_token": _csrf_token(client.get("/"))})

    _login_with_csrf(client, "qa.import@example.test", "temporary-password-123")
    preview = _preview_with_csrf(client, _energy_payload())
    response = client.post("/imports/standard", data=_confirm_data(preview))

    assert response.status_code == 200
    with app.app_context():
        created = db.session.execute(
            db.select(User).where(User.email == "qa.import@example.test")
        ).scalar_one()
        records = db.session.execute(db.select(DailyEnergy)).scalars().all()
        assert len(records) == 1
        assert records[0].user_id == created.id
        assert records[0].user_id != user


def test_standard_import_rejects_invalid_json(client, user):
    login(client)
    response = client.post(
        "/imports/standard",
        data={
            "target_type": "daily_energy",
            "file": (io.BytesIO(b"{not-json"), "bad.json"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"JSON" in response.data


def test_standard_import_empty_recipe_bundle_preview_has_no_confirm_button(client, user):
    login(client)
    payload = {
        "schema_version": "1.0",
        "type": "recipe_bundle",
        "user_id": user,
        "source_type": "uploaded",
        "recipes": [],
    }

    response = _preview(client, payload, target_type="recipe_bundle")

    assert response.status_code == 200
    assert b"recipe_bundle" in response.data
    assert b"Confirmar e importar" not in response.data
    try:
        _hidden(response, "confirmation_token")
    except AssertionError:
        pass
    else:
        raise AssertionError("invalid empty bundle should not get confirmation token")


def _energy_payload_to_standard(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "date": "2026-07-25",
            "source": "qa",
            "total_expenditure_kcal": 2400,
        },
    }
