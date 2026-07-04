import io
import json

from app.extensions import db
from app.models import UploadedFile, User
from tests.conftest import login


def _document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "type": "user_data_export",
        "exported_at": "2026-07-04T12:00:00+00:00",
        "user": {"id": user_id, "email": None, "role": "user"},
        "data": {
            "uploads": [],
            "weigh_ins": [],
            "daily_nutrition": [],
            "daily_energy": [],
            "daily_balances": [],
            "training_plans": [],
            "training_sessions": [],
            "medical_lab_reports": [],
        },
    }


def _post_json(client, document):
    return client.post(
        "/account/import-preview",
        data={
            "file": (
                io.BytesIO(json.dumps(document).encode("utf-8")),
                "fictional-export.json",
            )
        },
        content_type="multipart/form-data",
    )


def test_account_import_preview_requires_login(client):
    assert client.get("/account/import-preview").status_code == 302
    assert _post_json(client, _document(1)).status_code == 302


def test_account_import_preview_is_valid_and_never_writes(app, client, user):
    login(client)
    with app.app_context():
        before = {
            "users": db.session.execute(db.select(db.func.count(User.id))).scalar_one(),
            "uploads": db.session.execute(
                db.select(db.func.count(UploadedFile.id))
            ).scalar_one(),
        }

    response = _post_json(client, _document(user))

    assert response.status_code == 200
    assert b"Resultado del dry-run" in response.data
    assert b"No se realizaron escrituras" in response.data
    assert b"uploads" in response.data
    with app.app_context():
        after = {
            "users": db.session.execute(db.select(db.func.count(User.id))).scalar_one(),
            "uploads": db.session.execute(
                db.select(db.func.count(UploadedFile.id))
            ).scalar_one(),
        }
    assert after == before


def test_account_import_preview_shows_invalid_json_and_schema(app, client, user):
    login(client)
    invalid_json = client.post(
        "/account/import-preview",
        data={"file": (io.BytesIO(b"{not-json"), "invalid.json")},
        content_type="multipart/form-data",
    )
    assert invalid_json.status_code == 200
    assert b"no contiene JSON v" in invalid_json.data

    invalid_schema = _document(user)
    invalid_schema.pop("type")
    response = _post_json(client, invalid_schema)
    assert response.status_code == 200
    assert b"Inv" in response.data
    assert b"falta un campo requerido" in response.data
