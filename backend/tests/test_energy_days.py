"""Issue #18: synthetic values only; source evidence is never daily addition."""
import copy
from datetime import date
from decimal import Decimal
import json
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import DailyEnergy, EnergyDay, EnergyEvidenceEvent, User, DailyNutrition
from app.services import energy_days as energy, mobile_health
from app.services.daily_balance import daily_balance
from app.services.exporters.wellness import build_daily_energy_document, DailyEnergyCsvExporter
from app.services.importers.standard_import_executor import StandardImportExecutor
from app.services.nutrition_history import history
from app.services.validation import validate_json_document
from tests.conftest import login

DAY = date(2040, 2, 3)


def document(user, source='qa_device', day=DAY, **values):
    return {'schema_version':'1.0','record_type':'daily_energy','user_id':user,'source_type':'uploaded',
            'data':{'date':day.isoformat(),'source':source, **values}}


def put(user, source='qa_device', **values):
    row = energy.upsert_document(document(user, source, **values), user)
    db.session.commit()
    return row


def test_partial_full_sources_replay_null_zero_and_one_day(app, user):
    with app.app_context():
        first = put(user, 'qa_steps', steps=1200, distance_meters=800)
        identity, revision = first.public_id, first.revision
        put(user, total_expenditure_kcal=2400, active_expenditure_kcal=600, resting_expenditure_kcal=1800, steps=1200)
        result = energy.view(user, DAY)
        assert result.total_calories == 2400 and result.steps == 1200
        assert len(energy.views(user)) == db.session.query(EnergyDay).count() == 1
        assert db.session.query(DailyEnergy).count() == 2
        assert first.public_id == identity and first.revision == revision
        replay = put(user, total_expenditure_kcal=2400, active_expenditure_kcal=600, resting_expenditure_kcal=1800, steps=1200)
        current_revision = energy.view(user, DAY).revision
        put(user, total_expenditure_kcal=None, distance_meters=0)
        assert replay.total_calories == 2400 and replay.distance_meters == 0
        assert energy.view(user, DAY).distance_meters is None  # 800 vs a known zero
        assert energy.view(user, DAY).conflicts['distance_meters'] == ['0.00', '800.00']
        assert energy.view(user, DAY).revision > current_revision


def test_same_source_conflict_preserves_both_and_replay_revision(app, user):
    with app.app_context():
        row = put(user, total_expenditure_kcal=2200)
        original = copy.deepcopy(row.raw_payload_json)
        put(user, total_expenditure_kcal=2300)
        assert row.total_calories == 2200 and row.raw_payload_json == original
        pending = energy.view(user, DAY)
        assert pending.total_calories is None and len(pending.conflicts['total_calories']) == 2
        revision = pending.revision
        count = db.session.query(EnergyEvidenceEvent).count()
        put(user, total_expenditure_kcal=2300)
        assert energy.view(user, DAY).revision == revision
        assert db.session.query(EnergyEvidenceEvent).count() == count
        resolved = energy.edit_day(user, DAY, revision, {'total_calories': Decimal(2300)})
        db.session.commit()
        assert resolved.total_calories == 2300 and not resolved.conflicts
        put(user, total_expenditure_kcal=2350)
        assert energy.view(user, DAY).total_calories is None  # new disagreement needs review


def test_explicit_clear_date_collision_revision_and_owner(app, user):
    with app.app_context():
        row = put(user, total_expenditure_kcal=2200, steps=0)
        current = energy.view(user, DAY)
        cleared = energy.edit_day(user, DAY, current.revision, {}, clear=['total_calories'])
        db.session.commit()
        assert cleared.total_calories is None and cleared.steps == 0
        with pytest.raises(energy.EnergyConflict):
            energy.edit_day(user, DAY, current.revision, {'steps': 10})
        db.session.rollback()
        other = User(username='QA-energy-other', role='user');other.set_password('fictional')
        db.session.add(other);db.session.commit()
        assert energy.view(other.id, DAY) is None
        with pytest.raises(energy.EnergyConflict):
            energy.upsert_document(document(user, steps=10), other.id)
        db.session.rollback()
        target = date(2040, 2, 4)
        put(user, day=target, total_expenditure_kcal=2000)
        with pytest.raises(energy.EnergyConflict):
            energy.edit_day(user, DAY, energy.view(user, DAY).revision, {}, new_date=target)
        db.session.rollback()
        assert row.date == DAY and len(energy.views(user)) == 2


def test_delete_source_day_and_mobile_steps_keep_expenditure(app, user):
    with app.app_context():
        row = put(user, 'health_connect_aggregate', total_expenditure_kcal=2400, steps=1200)
        public_id = row.public_id
        mobile_health.delete_steps(user, public_id, {'base_revision':row.revision})
        db.session.commit()
        assert row.public_id == public_id and row.steps is None
        assert energy.view(user, DAY).total_calories == 2400
        step = mobile_health.create_steps(user, {'date':DAY.isoformat(),'source':'health_connect_aggregate','steps':1400,'client_event_id':str(uuid.uuid4())})
        db.session.commit()
        assert step.public_id == public_id
        put(user, 'qa_other', total_expenditure_kcal=2400)
        energy.delete_evidence(user, DAY, public_id, energy.view(user, DAY).revision)
        db.session.commit()
        assert energy.view(user, DAY).total_calories == 2400
        assert row.deleted_at is not None
        energy.delete_day(user, DAY, energy.view(user, DAY).revision)
        db.session.commit()
        assert energy.view(user, DAY) is None
        assert db.session.query(DailyEnergy).count() == 2
        assert db.session.query(EnergyEvidenceEvent).filter_by(kind='delete_day').count() == 1


def test_balance_trend_gaps_partial_conflict_no_double_count(app, user):
    with app.app_context():
        put(user, 'qa_a', total_expenditure_kcal=2400)
        put(user, 'qa_b', total_expenditure_kcal=2400, steps=1200)
        db.session.add(DailyNutrition(user_id=user, date=DAY, source='qa', calories=2000));db.session.commit()
        assert daily_balance(user, DAY)['balance'] == -400
        result = history(user, DAY, 7)
        assert result['points'][-1]['expended'] == 2400
        assert result['points'][0]['expended'] is None
        put(user, 'qa_c', total_expenditure_kcal=2500)
        assert daily_balance(user, DAY)['balance'] is None
        assert history(user, DAY, 7)['points'][-1]['expended'] is None


def test_energy_roundtrip_preserves_original_events_resolution_and_tombstone(app, user):
    with app.app_context():
        row = put(user, total_expenditure_kcal=2200, steps=0)
        put(user, total_expenditure_kcal=2300)
        energy.edit_day(user, DAY, energy.view(user, DAY).revision, {'total_calories':Decimal(2250)})
        db.session.commit()
        exported = build_daily_energy_document(energy.view(user, DAY), user)
        validate_json_document(exported, 'daily_energy')
        original_events = copy.deepcopy(exported['evidence']['sources'][0]['events'])
        other = User(username='QA-energy-restore', role='user');other.set_password('fictional')
        db.session.add(other);db.session.commit()
        exported['user_id'] = other.id
        restored = energy.upsert_document(exported, other.id);db.session.commit()
        assert restored.public_id != row.public_id
        assert energy.view(other.id, DAY).total_calories == 2250
        second = build_daily_energy_document(energy.view(other.id, DAY), other.id)
        assert second['evidence']['sources'][0]['events'] == original_events
        before = db.session.query(EnergyEvidenceEvent).count()
        energy.upsert_document(exported, other.id);db.session.commit()
        assert db.session.query(EnergyEvidenceEvent).count() == before
        assert DailyEnergyCsvExporter().export(energy.view(other.id, DAY), other.id).content


def test_standard_import_is_atomic_and_conservative(app, user):
    with app.app_context():
        executor = StandardImportExecutor()
        original = document(user, total_expenditure_kcal=2400)
        assert executor.commit_documents([original],user_id=user,target_type='daily_energy',confirmed=True)['committed']
        partial = document(user, total_expenditure_kcal=None, steps=0)
        assert executor.commit_documents([partial],user_id=user,target_type='daily_energy',confirmed=True)['committed']
        assert energy.view(user, DAY).total_calories == 2400 and energy.view(user, DAY).steps == 0
        bad = document(user, day=date(2040, 2, 4), steps=-1)
        assert not executor.commit_documents([document(user, day=date(2040, 2, 5), steps=1),bad],user_id=user,target_type='daily_energy',confirmed=True)['committed']
        assert energy.view(user, date(2040, 2, 5)) is None


def test_web_edit_delete_revision_csrf_and_owner(app, client, user):
    with app.app_context():
        row = put(user, total_expenditure_kcal=2400, steps=1200)
        record_id = row.id
        rev = energy.view(user, DAY).revision
    login(client)
    assert client.get(f'/daily-energy/{record_id}/edit').status_code == 200
    assert client.post(f'/daily-energy/{record_id}/edit',data={'date':DAY.isoformat(),'base_revision':rev,'steps':1300}).status_code == 302
    with app.app_context():
        assert energy.view(user, DAY).steps == 1300 and energy.view(user, DAY).total_calories == 2400
    assert client.post(f'/daily-energy/{record_id}/edit',data={'date':DAY.isoformat(),'base_revision':rev,'steps':1500}).status_code == 409
    assert client.get(f'/daily-energy/{record_id}/delete').status_code == 200
    with app.app_context():
        rev = energy.view(user, DAY).revision
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(f'/daily-energy/{record_id}/delete',data={'base_revision':rev,'confirm':'y'}).status_code == 400
    app.config['WTF_CSRF_ENABLED'] = False
    assert client.post(f'/daily-energy/{record_id}/delete',data={'base_revision':rev,'confirm':'y'}).status_code == 302
    assert client.get(f'/daily-energy/{record_id}').status_code == 404


def test_canonical_unique_constraint_and_rollback(app, user):
    with app.app_context():
        put(user, steps=1200)
        db.session.add(EnergyDay(user_id=user,date=DAY))
        with pytest.raises(IntegrityError):db.session.flush()
        db.session.rollback()
        assert len(energy.views(user)) == 1


def test_direct_upload_merge_and_zip_restore_preserve_file_hashes(app, client, user):
    import io
    from pathlib import Path
    from app.models import UploadedFile
    from app.services.backups import BackupRestoreCoordinator
    from tests.test_full_backup import _create_backup, _stage
    from tests.test_daily_energy import _import_energy
    login(client)
    first = document(user, steps=1200)
    second = document(user, steps=1200, total_expenditure_kcal=2400)
    assert _import_energy(client, first, 'QA-partial.json').status_code == 200
    assert _import_energy(client, second, 'QA-complete.json').status_code == 200
    with app.app_context():
        current = energy.view(user, DAY)
        assert current.total_calories == 2400
        assert db.session.query(DailyEnergy).count() == 1
        assert db.session.query(UploadedFile).count() == 2
        source_hashes = {row.sha256 for row in db.session.scalars(db.select(UploadedFile))}
        assert len(source_hashes) == 2
        events = list(db.session.scalars(db.select(EnergyEvidenceEvent)))
        assert {row.source_file_sha256 for row in events} == source_hashes
        _, backup_path = _create_backup(app, user)
        other = User(username='QA-energy-zip-destination', role='user');other.set_password('fictional')
        db.session.add(other);db.session.commit()
        coordinator = BackupRestoreCoordinator()
        staging = _stage(backup_path, coordinator, other.id)
        preview = coordinator.preview(staging_id=staging,user_id=other.id)
        result = coordinator.confirm(staging_id=staging,user_id=other.id,confirmation_token=preview['confirmation_token'])
        assert result['committed']
        restored = db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.user_id==other.id))
        assert energy.view(other.id, DAY).total_calories == 2400
        assert restored.source_file_id != current.source_file_id
        assert restored.source_file.sha256 == restored.source_file_sha256
        for event in db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id==other.id)):
            assert db.session.get(UploadedFile,event.source_file_id).user_id == other.id
        assert {row.sha256 for row in db.session.scalars(db.select(UploadedFile).where(UploadedFile.user_id==other.id))} == source_hashes


def test_confirmed_preview_binds_other_sources_and_current_revision(app, user):
    from app.services.importers.standard_import_executor import StandardImportTokenError
    with app.app_context():
        executor = StandardImportExecutor()
        incoming = document(user, total_expenditure_kcal=2400)
        plan = executor.plan_documents([incoming],user_id=user,target_type='daily_energy')
        token = executor.build_confirmation_token(user_id=user,target_type='daily_energy',payload=incoming,plan=plan)
        put(user,'qa_other_source',steps=1200)
        fresh = executor.plan_documents([incoming],user_id=user,target_type='daily_energy')
        # Both operations are still insert, but their canonical-day states differ.
        assert plan['operations'][0]['operation'] == fresh['operations'][0]['operation'] == 'insert'
        with pytest.raises(StandardImportTokenError,match='changed'):
            executor.verify_confirmation_token(token,user_id=user,target_type='daily_energy',payload=incoming,plan=fresh)


def test_csv_multi_day_provenance_and_signed_stale_confirmation(app, user):
    import io
    from werkzeug.datastructures import FileStorage
    from app.models import UploadedFile
    from app.services.files import store_uploaded_file
    from app.services.real_file_imports import RealFileImportService, RealFileImportTokenError
    with app.app_context():
        raw=b'date,total_calories,steps\n2040-02-03,2400,1200\n2040-02-04,2200,0\n'
        file,_=store_uploaded_file(FileStorage(stream=io.BytesIO(raw),filename='QA-energy.csv'),user)
        service=RealFileImportService()
        preview=service.preview_uploaded_file(file,user_id=user,requested_type='daily_energy_csv')
        put(user,'qa_device_before_confirmation',steps=1200)
        with pytest.raises(RealFileImportTokenError,match='changed'):
            service.confirm_uploaded_file(file,user_id=user,confirmation_token=preview['confirmation_token'],requested_type='daily_energy_csv')
        db.session.rollback()
        preview=service.preview_uploaded_file(file,user_id=user,requested_type='daily_energy_csv')
        result=service.confirm_uploaded_file(file,user_id=user,confirmation_token=preview['confirmation_token'],requested_type='daily_energy_csv')
        assert result['commit_result']['committed']
        assert len(energy.views(user))==2
        events=list(db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.source_file_id==file.id)))
        assert {item.date for item in events}=={DAY,date(2040,2,4)}
        assert all(item.source_file_sha256==file.sha256 for item in events)
        assert energy.view(user,date(2040,2,4)).steps==0


def test_mobile_event_mismatch_and_rich_source_date_move_are_rejected(app,user):
    from app.services.mobile_sync import MobileSyncError
    with app.app_context():
        event=str(uuid.uuid4())
        row=mobile_health.create_steps(user,{'date':DAY.isoformat(),'steps':1200,'client_event_id':event})
        db.session.commit();pid=row.public_id
        with pytest.raises(MobileSyncError):
            mobile_health.create_steps(user,{'date':DAY.isoformat(),'steps':1300,'client_event_id':event})
        db.session.rollback()
        put(user,'manual',total_expenditure_kcal=2400)
        with pytest.raises(MobileSyncError):
            mobile_health.patch_steps(user,pid,{'base_revision':row.revision,'date':'2040-02-04'})
        db.session.rollback()
        assert energy.view(user,DAY).total_calories==2400 and row.date==DAY


def test_import_rechecks_day_after_independent_audit_commit(app,user,monkeypatch):
    with app.app_context():
        executor=StandardImportExecutor()
        pending=executor.audit_service.record_pending
        def concurrent_commit(**kwargs):
            run=pending(**kwargs)
            # Another confirmed producer commits during the audit transaction gap.
            put(user,'qa_other_writer',steps=1200)
            return run
        monkeypatch.setattr(executor.audit_service,'record_pending',concurrent_commit)
        result=executor.commit_documents([document(user,total_expenditure_kcal=2400)],user_id=user,target_type='daily_energy',confirmed=True)
        assert not result['committed'] and result['rollback']
        assert {row.source for row in db.session.scalars(db.select(DailyEnergy))}=={'qa_other_writer'}
        assert energy.view(user,DAY).total_calories is None


def test_reformatted_file_preserves_origin_without_reopening_review(app,user):
    import io
    from werkzeug.datastructures import FileStorage
    from app.services.files import store_uploaded_file
    from app.services.importers.daily_energy import import_daily_energy_file
    with app.app_context():
        put(user,total_expenditure_kcal=2200)
        incoming=document(user,total_expenditure_kcal=2300)
        for indent in [None,4]:
            raw=json.dumps(incoming,indent=indent).encode()
            file,_=store_uploaded_file(FileStorage(stream=io.BytesIO(raw),filename='QA-reformatted.json'),user)
            row,_=import_daily_energy_file(file,user)
            if indent is None:
                energy.edit_day(user,DAY,energy.view(user,DAY).revision,{'total_calories':2250})
                db.session.commit()
                revision=energy.view(user,DAY).revision
        assert energy.view(user,DAY).total_calories==2250
        assert energy.view(user,DAY).revision==revision
        events=list(db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.source_file_id.is_not(None))))
        assert len(events)==2 and len({item.source_file_id for item in events})==2


def test_old_restore_cannot_overwrite_a_new_review_or_delete_decision(app,user):
    with app.app_context():
        put(user,total_expenditure_kcal=2200)
        energy.edit_day(user,DAY,energy.view(user,DAY).revision,{'total_calories':2250})
        db.session.commit()
        backup=build_daily_energy_document(energy.view(user,DAY),user)
        destination=User(username='QA-new-review-after-restore',role='user');destination.set_password('fictional')
        db.session.add(destination);db.session.commit()
        backup['user_id']=destination.id
        energy.upsert_document(backup,destination.id);db.session.commit()
        energy.edit_day(destination.id,DAY,energy.view(destination.id,DAY).revision,{'total_calories':2300})
        db.session.commit()
        with pytest.raises(energy.EnergyConflict):energy.upsert_document(backup,destination.id)
        db.session.rollback()
        assert energy.view(destination.id,DAY).total_calories==2300
        current_backup=build_daily_energy_document(energy.view(destination.id,DAY),destination.id)
        energy.delete_day(destination.id,DAY,energy.view(destination.id,DAY).revision);db.session.commit()
        with pytest.raises(energy.EnergyConflict):energy.upsert_document(current_backup,destination.id)
        db.session.rollback()
        assert energy.view(destination.id,DAY) is None


def test_manual_json_restore_retains_origin_without_inventing_raw_file(app,client,user):
    login(client)
    assert client.post('/manual/energy',data={'date':DAY.isoformat(),'total_calories':'2400','steps':'1200'}).status_code==302
    with app.app_context():
        backup=build_daily_energy_document(energy.view(user,DAY),user)
        assert backup['source_type']=='manual_generated'
        other=User(username='QA-manual-energy-json-restore',role='user');other.set_password('fictional')
        db.session.add(other);db.session.commit();backup['user_id']=other.id
        row=energy.upsert_document(backup,other.id);db.session.commit()
        restored=build_daily_energy_document(energy.view(other.id,DAY),other.id)
        assert row.source_file_id is None
        assert restored['source_type']=='manual_generated'
        assert restored['evidence']['sources'][0]['raw_payload']==backup['evidence']['sources'][0]['raw_payload']


def test_recreate_steps_retains_legacy_event_and_replays_additional_event(app,user):
    with app.app_context():
        first_event,second_event=str(uuid.uuid4()),str(uuid.uuid4())
        row=mobile_health.create_steps(user,{'date':DAY.isoformat(),'steps':1200,'client_event_id':first_event})
        db.session.commit();public_id=row.public_id
        mobile_health.delete_steps(user,public_id,{'base_revision':row.revision});db.session.commit()
        payload={'date':DAY.isoformat(),'steps':1300,'client_event_id':second_event}
        recreated=mobile_health.create_steps(user,payload);db.session.commit()
        revision=recreated.revision
        replay=mobile_health.create_steps(user,payload);db.session.commit()
        assert replay.public_id==public_id and replay.revision==revision
        assert replay.client_event_id==first_event
        assert energy.step_event(user,first_event) is not None
        assert energy.step_event(user,second_event) is not None
        other=User(username='QA-step-event-other',role='user');other.set_password('fictional');db.session.add(other);db.session.commit()
        assert energy.step_event(other.id,second_event) is None
