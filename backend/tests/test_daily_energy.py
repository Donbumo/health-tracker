import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import DailyEnergy, UploadedFile, User
from tests.conftest import login


def daily_energy_document(user_id: int, **data_overrides) -> dict:
    data = {
        "date": "2026-07-04",
        "total_expenditure_kcal": 2450.5,
        "active_expenditure_kcal": 650.25,
        "resting_expenditure_kcal": 1800.25,
        "steps": 9200,
        "distance_meters": 7100.5,
        "source": "fictional-test-device",
        "notes": "Fictional daily energy record",
    }
    data.update(data_overrides)
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": data,
    }


def _import_energy(client, document: dict, filename: str = "energy.json"):
    return client.post(
        "/daily-energy/import",
        data={"file": (io.BytesIO(json.dumps(document).encode("utf-8")), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_import_daily_energy_persists_source_and_deduplicates(app, client, user):
    login(client)
    document = daily_energy_document(user)
    response = _import_energy(client, document)
    assert response.status_code == 200
    assert b"Energ" in response.data

    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        record_id = record.id
        assert record.user_id == user
        assert record.total_calories == Decimal("2450.50")
        assert record.active_calories == Decimal("650.25")
        assert record.resting_calories == Decimal("1800.25")
        assert record.steps == 9200
        assert record.distance_meters == Decimal("7100.50")
        assert record.raw_payload_json == document
        assert source.detected_type == "daily_energy"
        assert source.import_status == "imported"

    duplicate = _import_energy(client, document, "same-energy.json")
    assert duplicate.status_code == 200
    with app.app_context():
        assert len(db.session.execute(db.select(DailyEnergy)).scalars().all()) == 1
        source = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert source.import_status == "duplicate"
    assert client.get(f"/daily-energy/{record_id}").status_code == 200


def test_daily_energy_optional_fields_and_invalid_json(app, client, user):
    login(client)
    optional_document = daily_energy_document(user)
    optional_document["data"] = {
        "date": "2026-07-05",
        "active_expenditure_kcal": 420,
        "steps": 6000,
    }
    assert _import_energy(client, optional_document).status_code == 200

    invalid_document = daily_energy_document(
        user,
        date="2026-07-06",
        total_expenditure_kcal=-1,
    )
    response = _import_energy(client, invalid_document, "invalid-energy.json")
    assert response.status_code == 200
    assert b"No fue posible importar" in response.data

    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        assert record.total_calories is None
        assert record.active_calories == Decimal("420.00")
        invalid_source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.import_status == "error")
        ).scalar_one()
        assert invalid_source.detected_type == "daily_energy"
        assert invalid_source.error_message


def test_daily_energy_is_isolated_by_user(app, client, user):
    login(client)
    document = daily_energy_document(user)
    _import_energy(client, document)
    with app.app_context():
        record = db.session.execute(db.select(DailyEnergy)).scalar_one()
        record_id = record.id
        second = User(username="energy-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    client.post("/logout")
    login(client, "energy-second-user", "second-password")
    assert client.get(f"/daily-energy/{record_id}").status_code == 404
    listing = client.get("/daily-energy")
    assert b"2026-07-04" not in listing.data

    rejected = _import_energy(client, document, "foreign-energy.json")
    assert b"does not belong to this user" in rejected.data
    with app.app_context():
        assert db.session.execute(
            db.select(DailyEnergy).where(DailyEnergy.user_id == second_id)
        ).scalar_one_or_none() is None
        source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == second_id)
        ).scalar_one()
        assert source.import_status == "error"
