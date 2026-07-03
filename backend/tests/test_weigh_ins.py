import io
import json
from decimal import Decimal

from app.extensions import db
from app.models import UploadedFile, User, WeighIn
from tests.conftest import login


def weigh_in_document(user_id: int, **data_overrides) -> dict:
    data = {
        "recorded_at": "2026-07-04T07:30:00+00:00",
        "weight_kg": 74.8,
        "body_fat_percent": 18.2,
        "muscle_mass_kg": 58.4,
        "water_percent": 56.1,
        "visceral_fat": 7,
        "bmr_kcal": 1720,
        "bmi": 23.6,
        "source": "fictional-test-scale",
        "notes": "Fictional weigh-in",
    }
    data.update(data_overrides)
    return {
        "schema_version": "1.0",
        "record_type": "weigh_in",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": data,
    }


def _import_weigh_in(client, document: dict, filename: str = "weigh-in.json"):
    return client.post(
        "/weigh-ins/import",
        data={"file": (io.BytesIO(json.dumps(document).encode("utf-8")), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_import_weigh_in_persists_body_composition_and_deduplicates(
    app,
    client,
    user,
):
    login(client)
    document = weigh_in_document(user)
    response = _import_weigh_in(client, document)
    assert response.status_code == 200
    assert "Pesaje importado correctamente".encode() in response.data

    with app.app_context():
        record = db.session.execute(db.select(WeighIn)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        record_id = record.id
        assert record.user_id == user
        assert record.weight_kg == Decimal("74.800")
        assert record.body_fat_percentage == Decimal("18.200")
        assert record.muscle_mass_kg == Decimal("58.400")
        assert record.water_percentage == Decimal("56.100")
        assert record.visceral_fat == Decimal("7.000")
        assert record.bmr_kcal == Decimal("1720.00")
        assert record.bmi == Decimal("23.600")
        assert record.raw_payload_json == document
        assert source.detected_type == "weigh_in"
        assert source.import_status == "imported"

    duplicate = _import_weigh_in(client, document, "same-weigh-in.json")
    assert duplicate.status_code == 200
    assert "ya había sido importado".encode() in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(WeighIn)).scalars().all()) == 1
        assert db.session.execute(db.select(UploadedFile)).scalar_one().import_status == "duplicate"
    assert client.get(f"/weigh-ins/{record_id}").status_code == 200


def test_weigh_in_optional_fields_and_invalid_json(app, client, user):
    login(client)
    minimal = weigh_in_document(user)
    minimal["data"] = {
        "recorded_at": "2026-07-05T08:00:00+00:00",
        "weight_kg": 75,
    }
    assert _import_weigh_in(client, minimal).status_code == 200

    invalid = weigh_in_document(
        user,
        recorded_at="2026-07-06T08:00:00+00:00",
        water_percent=101,
    )
    response = _import_weigh_in(client, invalid, "invalid-weigh-in.json")
    assert response.status_code == 200
    assert b"No fue posible importar" in response.data

    with app.app_context():
        record = db.session.execute(db.select(WeighIn)).scalar_one()
        assert record.body_fat_percentage is None
        assert record.muscle_mass_kg is None
        invalid_source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.import_status == "error")
        ).scalar_one()
        assert invalid_source.detected_type == "weigh_in"
        assert invalid_source.error_message


def test_manual_weigh_in_persists_extended_fields(app, client, user):
    login(client)
    response = client.post(
        "/manual/weigh-in",
        data={
            "recorded_at": "2026-07-07T07:15",
            "weight_kg": "74.5",
            "body_fat_percent": "18",
            "muscle_mass_kg": "58.2",
            "water_percent": "56.5",
            "visceral_fat": "7",
            "bmr_kcal": "1715",
            "bmi": "23.5",
            "notes": "Fictional manual record",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"74.500 kg" in response.data

    with app.app_context():
        record = db.session.execute(db.select(WeighIn)).scalar_one()
        source = db.session.get(UploadedFile, record.source_file_id)
        assert record.user_id == user
        assert record.source == "manual"
        assert record.muscle_mass_kg == Decimal("58.200")
        assert source.source_type == "manual_generated"
        assert source.detected_type == "weigh_in"
        assert source.import_status == "imported"


def test_weigh_ins_are_isolated_by_user(app, client, user):
    login(client)
    document = weigh_in_document(user)
    _import_weigh_in(client, document)
    with app.app_context():
        record_id = db.session.execute(db.select(WeighIn.id)).scalar_one()
        second = User(username="weigh-in-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    client.post("/logout")
    login(client, "weigh-in-second-user", "second-password")
    assert client.get(f"/weigh-ins/{record_id}").status_code == 404
    assert b"74.800" not in client.get("/weigh-ins").data

    rejected = _import_weigh_in(client, document, "foreign-weigh-in.json")
    assert b"does not belong to this user" in rejected.data
    with app.app_context():
        assert db.session.execute(
            db.select(WeighIn).where(WeighIn.user_id == second_id)
        ).scalar_one_or_none() is None
        source = db.session.execute(
            db.select(UploadedFile).where(UploadedFile.user_id == second_id)
        ).scalar_one()
        assert source.import_status == "error"
