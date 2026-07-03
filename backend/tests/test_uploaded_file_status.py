import hashlib
import io
import json

from app.extensions import db
from app.models import UploadedFile, User
from tests.conftest import login
from tests.test_phase_3 import training_plan_document


def test_generic_upload_tracks_pending_and_duplicate_status(app, client, user):
    login(client)
    payload = b"fictional pending upload\n"
    client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "pending.txt")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        record = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert record.detected_type == "unknown"
        assert record.import_status == "pending"
        assert record.error_message is None

    client.post(
        "/uploads",
        data={"file": (io.BytesIO(payload), "duplicate.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        record = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert record.import_status == "duplicate"
        assert record.error_message is None


def test_training_plan_import_tracks_success_error_and_duplicate(
    app,
    client,
    user,
):
    login(client)
    valid_payload = json.dumps(training_plan_document(user)).encode("utf-8")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(valid_payload), "valid-plan.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        valid_record = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.sha256 == hashlib.sha256(valid_payload).hexdigest()
            )
        ).scalar_one()
        assert valid_record.detected_type == "training_plan"
        assert valid_record.import_status == "imported"
        assert valid_record.error_message is None

    invalid_payload = b'{"not": "a valid training plan"}'
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(invalid_payload), "invalid-plan.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        invalid_record = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.sha256 == hashlib.sha256(invalid_payload).hexdigest()
            )
        ).scalar_one()
        assert invalid_record.detected_type == "training_plan"
        assert invalid_record.import_status == "error"
        assert invalid_record.error_message
        assert (
            app.config["DATA_ROOT"] / invalid_record.storage_path
        ).read_bytes() == invalid_payload

    client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(valid_payload), "same-plan.json")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        valid_record = db.session.execute(
            db.select(UploadedFile).where(
                UploadedFile.sha256 == hashlib.sha256(valid_payload).hexdigest()
            )
        ).scalar_one()
        assert valid_record.import_status == "duplicate"


def test_import_status_records_remain_isolated_by_user(app, client, user):
    login(client)
    payload = json.dumps(training_plan_document(user)).encode("utf-8")
    client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "owner-plan.json")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        second = User(username="status-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    client.post("/logout")
    login(client, "status-second-user", "second-password")
    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(payload), "foreign-plan.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        records = db.session.execute(
            db.select(UploadedFile).order_by(UploadedFile.user_id)
        ).scalars().all()
        assert len(records) == 2
        owner_record = next(item for item in records if item.user_id == user)
        second_record = next(item for item in records if item.user_id == second_id)
        assert owner_record.import_status == "imported"
        assert second_record.import_status == "error"
        assert second_record.detected_type == "training_plan"
        assert owner_record.sha256 == second_record.sha256
