import io
import json
from decimal import Decimal

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import MedicalLabReport, UploadedFile, User
from app.services.files import store_uploaded_file
from app.services.importers.medical_lab import (
    MedicalLabImportError,
    import_medical_lab_file,
)
from app.services.validation import JsonSchemaValidationError
from tests.test_medical_lab_schema import medical_lab_document


def _store_document(document: dict, user_id: int, filename: str = "lab.json"):
    payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return store_uploaded_file(
        FileStorage(
            stream=io.BytesIO(payload),
            filename=filename,
            content_type="application/json",
        ),
        user_id,
    )


def test_medical_lab_import_persists_markers_source_and_status(app, user):
    document = medical_lab_document(user)
    with app.app_context():
        source, file_duplicate = _store_document(document, user)
        report, report_duplicate = import_medical_lab_file(source, user)

        assert file_duplicate is False
        assert report_duplicate is False
        assert report.source_file_id == source.id
        assert report.raw_payload_json == document
        assert len(report.results) == 2
        assert report.results[0].value == Decimal("12.500000")
        assert report.results[1].value_text == "no reactivo ficticio"
        assert source.detected_type == "medical_lab"
        assert source.import_status == "imported"
        assert source.error_message is None


def test_medical_lab_import_deduplicates_by_user_and_sha(app, user):
    document = medical_lab_document(user)
    with app.app_context():
        source, _ = _store_document(document, user)
        first, duplicate = import_medical_lab_file(source, user)
        assert duplicate is False

        same_source, file_duplicate = _store_document(
            document,
            user,
            "same-report.json",
        )
        second, report_duplicate = import_medical_lab_file(same_source, user)
        assert file_duplicate is True
        assert report_duplicate is True
        assert second.id == first.id
        assert same_source.import_status == "duplicate"
        assert len(db.session.execute(db.select(MedicalLabReport)).scalars().all()) == 1


def test_invalid_medical_lab_json_keeps_file_with_clear_error(app, user):
    invalid = medical_lab_document(user)
    invalid["markers"] = []
    with app.app_context():
        source, _ = _store_document(invalid, user, "invalid-lab.json")
        with pytest.raises(JsonSchemaValidationError):
            import_medical_lab_file(source, user)

        assert source.detected_type == "medical_lab"
        assert source.import_status == "error"
        assert "markers" in source.error_message
        assert db.session.execute(db.select(MedicalLabReport)).scalar_one_or_none() is None


def test_medical_lab_import_is_isolated_by_user(app, user):
    document = medical_lab_document(user)
    with app.app_context():
        second = User(username="medical-import-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

        source, _ = _store_document(document, second.id, "foreign-lab.json")
        with pytest.raises(MedicalLabImportError, match="does not belong"):
            import_medical_lab_file(source, second.id)

        assert source.import_status == "error"
        assert source.user_id == second.id
        assert db.session.execute(
            db.select(MedicalLabReport).where(MedicalLabReport.user_id == second.id)
        ).scalar_one_or_none() is None

        with pytest.raises(MedicalLabImportError, match="does not belong"):
            import_medical_lab_file(source, user)
        stored = db.session.execute(db.select(UploadedFile)).scalar_one()
        assert stored.user_id == second.id
