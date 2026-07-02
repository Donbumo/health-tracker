import io
import json

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, UploadedFile, User
from app.services.validation import validate_json_document
from tests.conftest import login


def training_plan_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "uploaded",
        "data": {
            "name": "Fictional Foundation Plan",
            "description": "A fictional plan used only by automated tests.",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Strength day",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Example squat",
                                    "sets": [
                                        {"set_number": 1, "reps": 8, "rest_seconds": 90},
                                        {"set_number": 2, "reps": 8, "rest_seconds": 90},
                                    ],
                                }
                            ],
                        },
                        {
                            "day_number": 2,
                            "name": "Rest day",
                            "exercises": [],
                        },
                    ],
                }
            ],
        },
    }


def _json_upload(document: dict, filename: str = "training-plan.json") -> dict:
    payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return {"file": (io.BytesIO(payload), filename)}


def test_training_plan_schema_accepts_minimum_plan(app, user):
    with app.app_context():
        validate_json_document(training_plan_document(user), "training_plan")


def test_import_list_detail_export_and_deduplicate_plan(app, client, user):
    document = training_plan_document(user)
    original_bytes = json.dumps(document, ensure_ascii=False).encode("utf-8")
    login(client)

    response = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(original_bytes), "foundation.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Rutina importada como versi" in response.data
    assert b"Fictional Foundation Plan" in response.data

    with app.app_context():
        plan = db.session.execute(db.select(TrainingPlan)).scalar_one()
        version = db.session.execute(db.select(TrainingPlanVersion)).scalar_one()
        source_file = db.session.execute(db.select(UploadedFile)).scalar_one()
        plan_id = plan.id

        assert plan.user_id == user
        assert plan.active_version_number == 1
        assert version.user_id == user
        assert version.training_plan_id == plan.id
        assert version.version_number == 1
        assert version.source_file_id == source_file.id
        assert version.content == document
        assert source_file.user_id == user
        assert source_file.source_type == "uploaded"

        raw_path = app.config["DATA_ROOT"] / source_file.storage_path
        assert raw_path.read_bytes() == original_bytes

    listing = client.get("/training-plans")
    assert listing.status_code == 200
    assert b"Fictional Foundation Plan" in listing.data

    detail = client.get(f"/training-plans/{plan_id}")
    assert detail.status_code == 200
    assert b"Versi" in detail.data
    assert b"Example squat" in detail.data

    exported = client.get(f"/training-plans/{plan_id}/export")
    assert exported.status_code == 200
    assert exported.mimetype == "application/json"
    assert "attachment" in exported.headers["Content-Disposition"]
    assert json.loads(exported.data) == document

    duplicate = client.post(
        "/training-plans/import",
        data={"file": (io.BytesIO(original_bytes), "same-plan.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"ya hab" in duplicate.data
    with app.app_context():
        assert len(db.session.execute(db.select(TrainingPlan)).scalars().all()) == 1
        assert len(db.session.execute(db.select(TrainingPlanVersion)).scalars().all()) == 1
        assert len(db.session.execute(db.select(UploadedFile)).scalars().all()) == 1


def test_invalid_plan_keeps_source_file_without_importing(app, client, user):
    invalid = training_plan_document(user)
    del invalid["data"]["weeks"]
    login(client)

    response = client.post(
        "/training-plans/import",
        data=_json_upload(invalid, "invalid-plan.json"),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"No fue posible importar" in response.data

    with app.app_context():
        assert db.session.execute(db.select(UploadedFile)).scalar_one().user_id == user
        assert db.session.execute(db.select(TrainingPlan)).scalar_one_or_none() is None
        assert db.session.execute(db.select(TrainingPlanVersion)).scalar_one_or_none() is None


def test_plan_owner_must_match_and_other_users_cannot_access(app, client, user):
    document = training_plan_document(user)
    login(client)
    client.post(
        "/training-plans/import",
        data=_json_upload(document),
        content_type="multipart/form-data",
    )

    with app.app_context():
        plan_id = db.session.execute(db.select(TrainingPlan.id)).scalar_one()
        second = User(username="training-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    client.post("/logout")
    login(client, "training-second-user", "second-password")
    assert b"Fictional Foundation Plan" not in client.get("/training-plans").data
    assert client.get(f"/training-plans/{plan_id}").status_code == 404
    assert client.get(f"/training-plans/{plan_id}/export").status_code == 404

    mismatch = training_plan_document(user)
    response = client.post(
        "/training-plans/import",
        data=_json_upload(mismatch, "wrong-owner.json"),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"user_id does not match" in response.data

    with app.app_context():
        assert len(db.session.execute(db.select(TrainingPlan)).scalars().all()) == 1
