"""Issue #50 reproductions using exclusively fictitious catalog and account data."""

from copy import deepcopy
import json
from zipfile import ZipFile

import pytest

from app.extensions import db
from app.models import ExportRecord, MealLog, User
from app.services import food_catalog as catalog, nutrition_intelligence as ni
from app.services.backups import AccountBackupService, BackupArchiveReader, BackupRestoreCoordinator
from app.services.exporters.user_data import build_user_data_document
from app.services.nutrition_portability import export_bundle
from app.services.nutrition_sources import off_food
from app.services.validation import JsonSchemaValidationError, validate_json_document
from tests.conftest import login
from tests.test_full_backup import _source_account, _stage
from tests.test_nutrition_import_source_21 import app  # SQLite or isolated MariaDB 0046
from tests.test_nutrition_intelligence import food


def save_catalog_meal(app, owner_id, *, version):
    app.config["NUTRITION_INTELLIGENCE_ENABLED"] = True
    community_evidence = off_food({
        "code": "0000000000001",
        "product_name": "Etiqueta ficticia QA",
        "nutrition_data_per": "100g",
        "nutriments": {
            "carbohydrates_100g": "12.125",
            "vitamin-c_100g": "10",
            "vitamin-c_unit": "%",
        },
    })["provenance"]
    portions_evidence = {
        "method": "FDC ficticio QA",
        "original_servings": [
            {"id": "qa-cup", "gram_weight": "158.000", "description": "1 taza ficticia"},
        ],
    }
    foods = [
        dict(food(), source_food_id="QA_AMBIGUOUS", name="Alimento ficticio QA A",
             provenance=community_evidence),
        dict(food(), source_food_id="QA_PORTIONS", name="Alimento ficticio QA B",
             provenance=portions_evidence),
    ]
    if version == "2.1":
        foods[1]["metadata"] = {"aliases": ["Porción ficticia QA"]}
    catalog.stage({
        "schema_version": "2.0", "source": "qa_fictional", "revision": "1",
        "license": "QA synthetic", "foods": foods,
    })
    catalog.activate("qa_fictional", "1", 1)
    db.session.commit()

    result = catalog.search(owner_id)
    draft = ni.create_draft(owner_id, target="2031-04-18", name="Comida ficticia QA",
                            entries=[{"ref": row["ref"], "amount": "180", "unit": "g"} for row in result])
    for index in range(len(foods)):
        draft = ni.mutate_draft(owner_id, draft.public_id, draft.revision, "accept", {"index": index})
    log, _ = ni.confirm(owner_id, ni.confirmation_token(draft))
    db.session.commit()
    snapshot = deepcopy(log.snapshot_json)
    assert snapshot["schema_version"] == version
    assert [entry["food"]["provenance"] for entry in snapshot["ingredients"]] == [
        community_evidence, portions_evidence,
    ]
    return snapshot


@pytest.mark.parametrize("version", ["2.0", "2.1"])
def test_account_json_exports_historical_catalog_evidence(app, client, user, version):
    snapshot = save_catalog_meal(app, user, version=version)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    login(client)
    response = client.get("/account/export.json")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "attachment" in response.headers["Content-Disposition"]
    document = json.loads(response.data)
    validate_json_document(document, "user_data_export")
    bundle, = document["data"]["nutrition_intelligence"]
    validate_json_document(bundle, "nutrition_intelligence_2")
    assert bundle["schema_version"] == version
    assert len(bundle["logs"]) == len(bundle["authorities"]) == 1
    assert bundle["logs"][0]["snapshot"] == snapshot
    assert db.session.query(MealLog).filter_by(user_id=user).one().snapshot_json == snapshot
    assert db.session.query(ExportRecord).filter_by(user_id=user).count() == 0


def test_account_zip_preview_download_and_restore_preserve_catalog_evidence(app, client, user):
    snapshot = save_catalog_meal(app, user, version="2.1")
    source = _source_account(app, user)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    login(client)
    assert client.get("/account/backups/new").status_code == 200
    assert client.post("/account/backups/new", data={}).status_code == 302
    record = db.session.query(ExportRecord).filter_by(user_id=user, domain="account_backup").one()
    download_url = f"/account/backups/{record.id}/download"
    download = client.get(download_url)
    assert download.status_code == 200
    assert download.mimetype == "application/zip"
    path = AccountBackupService().resolve_download(record, user_id=user)
    assert path.read_bytes() == download.data
    with ZipFile(path) as archive:
        assert archive.testzip() is None
    inspection = BackupArchiveReader().inspect(path)
    validate_json_document(inspection.account_payload, "user_data_export")
    assert inspection.account_payload["data"]["nutrition_intelligence"][0]["logs"][0]["snapshot"] == snapshot
    assert source["raw_sha"] in {entry["sha256"] for entry in inspection.manifest["entries"]}

    target = User(username="qa-incident-50-restore", role="user")
    target.set_password("fictional-test-password")
    db.session.add(target)
    db.session.commit()
    target_id = target.id
    with app.app_context():
        foreign = app.test_client()
        login(foreign, username="qa-incident-50-restore", password="fictional-test-password")
        assert foreign.get(download_url).status_code == 404
        other_export = json.loads(foreign.get("/account/export.json").data)
        assert "nutrition_intelligence" not in other_export["data"]

    restore = BackupRestoreCoordinator()
    staging_id = _stage(path, restore, target_id)
    preview = restore.preview(staging_id=staging_id, user_id=target_id)
    assert export_bundle(target_id) is None
    assert restore.confirm(staging_id=staging_id, user_id=target_id,
                           confirmation_token=preview["confirmation_token"])["committed"]
    assert export_bundle(target_id)["logs"][0]["snapshot"] == snapshot
    assert db.session.query(MealLog).filter_by(user_id=user).one().snapshot_json == snapshot


def test_food_provenance_schema_keeps_legacy_scalars_and_rejects_other_structures(app, user):
    save_catalog_meal(app, user, version="2.0")
    document = build_user_data_document(db.session.get(User, user), user)
    bundle, = document["data"]["nutrition_intelligence"]
    provenance = bundle["logs"][0]["snapshot"]["ingredients"][0]["food"]["provenance"]
    provenance["ambiguous_fields"] = "Nota histórica ficticia"
    provenance["original_servings"] = None
    validate_json_document(bundle, "nutrition_intelligence_2")
    validate_json_document(document, "user_data_export")
    for key, invalid in [
        ("unknown_extension", {"nested": "dato ficticio"}),
        ("ambiguous_fields", {"energy": {"value": [], "classification": "ficticia"}}),
        ("original_servings", [{"id": "qa", "gram_weight": {"amount": "12"}, "description": "QA"}]),
    ]:
        altered_document = deepcopy(document)
        mutated, = altered_document["data"]["nutrition_intelligence"]
        mutated["logs"][0]["snapshot"]["ingredients"][0]["food"]["provenance"][key] = invalid
        with pytest.raises(JsonSchemaValidationError):
            validate_json_document(mutated, "nutrition_intelligence_2")
        with pytest.raises(JsonSchemaValidationError):
            validate_json_document(altered_document, "user_data_export")
