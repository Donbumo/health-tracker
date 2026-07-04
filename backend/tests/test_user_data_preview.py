import json

from app.services.importers.user_data_preview import preview_user_data_import


def _payload(user_id: int = 1) -> dict:
    return {
        "schema_version": "1.0",
        "type": "user_data_export",
        "exported_at": "2026-07-04T12:00:00+00:00",
        "user": {"id": user_id, "email": "preview@example.test", "role": "user"},
        "data": {
            "uploads": [{"id": 1}],
            "weigh_ins": [],
            "daily_nutrition": [{"record": "fictional"}],
            "daily_energy": [],
            "daily_balances": [],
            "training_plans": [],
            "training_sessions": [],
            "medical_lab_reports": [],
        },
    }


def test_preview_summarizes_valid_export_without_writes(app):
    with app.app_context():
        preview = preview_user_data_import(_payload(), current_user_id=1)

    assert preview["valid"] is True
    assert preview["dry_run"] is True
    assert preview["writes_performed"] is False
    assert preview["errors"] == []
    assert preview["counts"]["uploads"] == 1
    assert preview["counts"]["daily_nutrition"] == 1
    assert preview["warnings"] == []


def test_preview_warns_for_other_user_and_missing_sections(app):
    payload = _payload(user_id=99)
    payload["data"].pop("medical_lab_reports")

    with app.app_context():
        preview = preview_user_data_import(payload, current_user_id=1)

    assert preview["valid"] is True
    assert any("otro identificador" in warning for warning in preview["warnings"])
    assert any("medical_lab_reports" in warning for warning in preview["warnings"])


def test_preview_invalid_payload_never_echoes_sensitive_fields_or_values(app):
    payload = _payload()
    payload["user"]["password_hash"] = "fictional-super-secret-hash"
    payload["data"]["token"] = [{"value": "fictional-secret-token"}]

    with app.app_context():
        preview = preview_user_data_import(payload, current_user_id=1)

    serialized = json.dumps(preview)
    assert preview["valid"] is False
    assert preview["errors"]
    assert preview["writes_performed"] is False
    assert "password_hash" not in serialized
    assert "fictional-super-secret-hash" not in serialized
    assert "fictional-secret-token" not in serialized
    assert "token" not in preview["sections"]


def test_preview_warns_for_unexpected_schema_version_without_leaking_payload(app):
    payload = _payload()
    payload["schema_version"] = "999.0"

    with app.app_context():
        preview = preview_user_data_import(payload)

    assert preview["valid"] is False
    assert any("1.0" in warning for warning in preview["warnings"])
