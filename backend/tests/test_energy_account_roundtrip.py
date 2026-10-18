"""PR #21 control 1: complete synthetic account, never real health data."""
import copy
import hashlib
import io
import json
from datetime import date
from pathlib import Path
import uuid

import pytest
from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, EnergyDay, EnergyEvidenceEvent, UploadedFile, User
from app.services import energy_days as energy, mobile_health
from app.services.account_restore import AccountRestoreService
from app.services.backups import BackupRestoreCoordinator
from app.services.daily_balance import daily_balance
from app.services.exporters.user_data import build_user_data_document
from app.services.files import store_uploaded_file
from app.services.importers.daily_energy import import_daily_energy_file
from app.services.nutrition_history import history
from tests.test_energy_days import document
from tests.test_full_backup import _create_backup, _stage

DAY = date(2040, 2, 3)


def make_owner():
    row = User(username='QA-control21-' + uuid.uuid4().hex, role='user')
    row.set_password('fictional-QA-only')
    db.session.add(row)
    db.session.commit()
    return row.id


def seed_account(user_id):
    """Four original files, mobile revisions, conflict/review and retired source."""
    for source, values in [
        ('qa_steps', {'steps': 1200, 'distance_meters': 800}),
        ('qa_expenditure', {'total_expenditure_kcal': 2400, 'active_expenditure_kcal': 600}),
        ('qa_expenditure', {'total_expenditure_kcal': 2500}),
        ('qa_retired', {'total_expenditure_kcal': 2100}),
    ]:
        payload = document(user_id, source, **values)
        original = json.dumps(payload, indent=2).encode()
        upload, _ = store_uploaded_file(FileStorage(stream=io.BytesIO(original), filename=f'QA-{source}-{len(original)}.json'), user_id)
        import_daily_energy_file(upload, user_id)
    assert energy.view(user_id, DAY).total_calories is None
    energy.edit_day(user_id, DAY, energy.view(user_id, DAY).revision, {'total_calories': 2450})
    db.session.commit()
    retired = db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.user_id == user_id, DailyEnergy.source == 'qa_retired'))
    energy.delete_evidence(user_id, DAY, retired.public_id, energy.view(user_id, DAY).revision)
    db.session.commit()
    event_id = str(uuid.uuid4())
    mobile = mobile_health.create_steps(user_id, {'date': DAY.isoformat(), 'source': 'health_connect_aggregate', 'steps': 1200, 'client_event_id': event_id})
    db.session.commit()
    mobile_health.patch_steps(user_id, mobile.public_id, {'base_revision': mobile.revision, 'steps': 1300})
    db.session.commit()
    mobile_health.patch_steps(user_id, mobile.public_id, {'base_revision': mobile.revision, 'steps': 1200})
    db.session.commit()
    # A fully deleted second date must also survive account/ZIP exports.
    energy.upsert_document(document(user_id, 'qa_deleted_day', day=date(2040, 2, 4), steps=0), user_id)
    db.session.commit()
    energy.delete_day(user_id, date(2040, 2, 4), energy.view(user_id, date(2040, 2, 4)).revision)
    db.session.add(DailyNutrition(user_id=user_id, date=DAY, source='qa', calories=2000))
    db.session.commit()
    assert energy.view(user_id, DAY).total_calories == 2450


def semantic_evidence(user_id):
    export = build_user_data_document(db.session.get(User, user_id), user_id)
    result = []
    for doc in export['data']['daily_energy']:
        item = copy.deepcopy(doc)
        item.pop('user_id')
        for source in item['evidence']['sources']:
            # Only live global UUIDs may remap; immutable event payloads stay exact.
            source.pop('public_id')
        result.append(item)
    return sorted(result, key=lambda row: (row['data']['date'], row['data']['source']))


def assert_account(user_id, original, source_ids, source_events, source_hashes, *, with_files):
    assert semantic_evidence(user_id) == original
    assert len(energy.views(user_id)) == 1
    assert db.session.query(EnergyDay).filter_by(user_id=user_id).count() == 2
    assert daily_balance(user_id, DAY)['balance'] == -450
    points = history(user_id, DAY, 7)['points']
    assert points[-1]['expended'] == 2450 and points[0]['expended'] is None
    sources = list(db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == user_id)))
    assert len(sources) == 5 and len({row.public_id for row in sources}) == 5
    assert not source_ids.intersection(row.public_id for row in sources)
    events = list(db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == user_id)))
    assert {row.event_key: row.payload_json for row in events} == source_events
    assert {row.evidence_public_id for row in events} <= {row.public_id for row in sources}
    if with_files:
        files = list(db.session.scalars(db.select(UploadedFile).where(UploadedFile.user_id == user_id)))
        assert {row.sha256 for row in files} == source_hashes
        for row in files:
            content = (Path(current_app.config['DATA_ROOT']) / row.storage_path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == row.sha256
        for row in [*sources, *events]:
            if row.source_file_id is not None:
                upload = db.session.get(UploadedFile, row.source_file_id)
                assert upload.user_id == user_id and upload.sha256 == row.source_file_sha256
    else:
        assert all(row.source_file_id is None for row in [*sources, *events])


@pytest.mark.parametrize('mode', ['json', 'zip'])
def test_complete_energy_account_roundtrip(app, user, mode):
    with app.app_context():
        seed_account(user)
        original = semantic_evidence(user)
        source_ids = {row.public_id for row in db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == user))}
        source_events = {row.event_key: copy.deepcopy(row.payload_json) for row in db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == user))}
        source_hashes = {row.sha256 for row in db.session.scalars(db.select(UploadedFile).where(UploadedFile.user_id == user))}
        assert len(source_hashes) == 4
        original_points = copy.deepcopy(history(user, DAY, 7)['points'])
        payload = build_user_data_document(db.session.get(User, user), user)
        _, archive = _create_backup(app, user)
        destination = make_owner()

        def restore():
            if mode == 'json':
                service = AccountRestoreService()
                preview = service.preview(payload, user_id=destination)
                return service.commit(payload, user_id=destination, confirmation_token=preview['confirmation_token'])
            coordinator = BackupRestoreCoordinator()
            staged = _stage(archive, coordinator, destination)
            preview = coordinator.preview(staging_id=staged, user_id=destination)
            return coordinator.confirm(staging_id=staged, user_id=destination, confirmation_token=preview['confirmation_token'])

        assert restore()['committed']
        assert_account(destination, original, source_ids, source_events, source_hashes, with_files=mode == 'zip')
        assert history(destination, DAY, 7)['points'] == original_points
        mobile = db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.user_id == destination, DailyEnergy.source == 'health_connect_aggregate'))
        mobile_identity = (mobile.public_id, mobile.revision)
        assert mobile.revision == 3 and energy.step_event(destination, mobile.client_event_id) is not None
        replay = mobile_health.create_steps(destination, {'date': DAY.isoformat(), 'source': mobile.source, 'steps': 1200, 'client_event_id': mobile.client_event_id})
        db.session.commit()
        assert (replay.public_id, replay.revision) == mobile_identity
        first_ids = {(row.public_id, row.revision) for row in db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == destination))}
        assert restore()['committed']
        assert_account(destination, original, source_ids, source_events, source_hashes, with_files=mode == 'zip')
        assert {(row.public_id, row.revision) for row in db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == destination))} == first_ids
        assert semantic_evidence(user) == original  # source owner untouched
        # Stale backup cannot replace a newer explicit review or undo a tombstone.
        energy.edit_day(destination, DAY, energy.view(destination, DAY).revision, {'total_calories': 2460})
        db.session.commit()
        assert not restore()['committed']
        assert energy.view(destination, DAY).total_calories == 2460
        energy.delete_day(destination, DAY, energy.view(destination, DAY).revision)
        db.session.commit()
        assert not restore()['committed']
        assert energy.view(destination, DAY) is None


def test_legacy_10_account_restore_remains_conservative(app, user):
    with app.app_context():
        payload = build_user_data_document(db.session.get(User, user), user)
        payload['data']['daily_energy'] = [document(user, 'qa_legacy', steps=0, total_expenditure_kcal=2400)]
        service = AccountRestoreService()
        for _ in range(2):
            preview = service.preview(payload, user_id=user)
            result = service.commit(payload, user_id=user, confirmation_token=preview['confirmation_token'])
            assert result['committed']
        assert db.session.query(DailyEnergy).filter_by(user_id=user).count() == 1
        energy.upsert_document(document(user, 'qa_legacy', total_expenditure_kcal=None), user)
        db.session.commit()
        assert energy.view(user, DAY).steps == 0 and energy.view(user, DAY).total_calories == 2400
