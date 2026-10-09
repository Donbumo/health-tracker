"""Deletion safety with fictional routines only; no production data."""
from datetime import date, datetime, timezone
import re
import uuid
import hashlib

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import (Exercise, ExerciseAlias, PlannedWorkout, SyncChange, TrainingPlan,
                        TrainingPlanVersion, TrainingPlanWorkout, TrainingSession,
                        TrainingSet, UploadedFile, User, WorkoutSessionDraft)
from app.services.gym_delete import delete_program
from app.services.gym_programs import GymError, preset_draft
from app.services.gym_capabilities import read_program, read_session
from app.services.gym_sessions import complete_set, finish_session
from app.services.mobile_sync import PlannedWorkoutService
from app.services.training_plans import get_active_version
from tests.conftest import login
from tests.test_gym_training import program, start
from tests.test_mobile_sync import _api_login, _auth
from tests.test_mobile_planning import _create_plan, _headers


@pytest.fixture(autouse=True)
def enforce_foreign_keys(app):
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
    db.session.commit()


def remove(owner, public_id, revision=1):
    return delete_program(owner, public_id, base_revision=revision, confirmation='ELIMINAR')


@pytest.mark.parametrize('archived', [False, True])
def test_delete_cascades_only_unused_plan_and_is_idempotent(app, user, archived):
    plan = program(user)
    source_path = app.config['UPLOAD_ROOT'] / 'fictional-delete-source.txt'
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('Fictional QA routine source', encoding='utf-8')
    upload = UploadedFile(user_id=user, original_filename=source_path.name, stored_filename=source_path.name,
        storage_path=str(source_path), sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        size_bytes=source_path.stat().st_size, import_status='imported')
    db.session.add(upload)
    db.session.flush()
    get_active_version(plan, user).source_file_id = upload.id
    db.session.commit()
    plan = program(user, draft=preset_draft('full-body-v1'), plan=plan)
    plan.status = 'archived' if archived else 'active'
    db.session.commit()
    public_id, revision, plan_id = plan.public_id, plan.revision, plan.id
    preserved = {model: db.session.query(model).count() for model in (Exercise, ExerciseAlias, UploadedFile)}
    assert db.session.query(TrainingPlanVersion).filter_by(training_plan_id=plan_id).count() == 2
    assert remove(user, public_id, revision)
    db.session.commit()
    assert not remove(user, public_id, revision)
    db.session.commit()
    for model in (TrainingPlanVersion, TrainingPlanWorkout):
        assert db.session.query(model).filter_by(training_plan_id=plan_id).count() == 0
    assert db.session.query(TrainingPlan).filter_by(public_id=public_id).count() == 0
    for model, count in preserved.items():
        assert db.session.query(model).count() == count
    assert source_path.read_text(encoding='utf-8') == 'Fictional QA routine source'
    changes = db.session.query(SyncChange).filter_by(entity_public_id=public_id, operation='delete').all()
    assert len(changes) == 1 and changes[0].revision == revision + 1


@pytest.mark.parametrize('status', ['in_progress', 'completed', 'abandoned', 'deleted'])
def test_every_session_preserved_including_soft_deleted(app, user, status):
    plan = program(user)
    session = start(user, plan)
    complete_set(user, session.public_id, 1, 1, {'load':'40', 'unit':'kg', 'reps':'8', 'rir':'2'})
    if status != 'in_progress':
        finish_session(user, session.public_id, 'completed' if status == 'deleted' else status)
    if status == 'deleted':
        session.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    identifiers = session.id, session.training_plan_id, session.training_plan_version_id
    if status == 'in_progress':
        with pytest.raises(GymError) as error:
            remove(user, plan.public_id, plan.revision)
        assert error.value.status == 409
        db.session.rollback()
    else:
        public_id, revision = plan.public_id, plan.revision
        assert remove(user, public_id, revision)
        db.session.commit()
        assert plan.deleted_at is not None and not plan.gym_active
        assert not remove(user, public_id, revision)
        db.session.commit()
        assert db.session.query(TrainingPlanWorkout).count() == 0
    assert db.session.query(TrainingSet).filter_by(user_id=user).count() == 1
    assert (session.id, session.training_plan_id, session.training_plan_version_id) == identifiers
    assert db.session.query(SyncChange).filter_by(operation='delete').count() == int(status != 'in_progress')
    if status != 'deleted':
        assert read_session(user, session.public_id)['session_id'] == session.public_id


@pytest.mark.parametrize('status', ['planned', 'in_progress', 'completed', 'skipped', 'cancelled', 'deleted'])
def test_agenda_references_preserved(app, user, status):
    plan = program(user)
    row = PlannedWorkoutService.schedule_from_plan_version(user_id=user, plan_public_id=plan.public_id,
        version_public_id=None, scheduled_for_date=date(2026, 9, 18), timezone_name='UTC', week_number=1, day_number=1)
    row.status = 'cancelled' if status == 'deleted' else status
    if status == 'deleted':
        row.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    if status in ('planned', 'in_progress'):
        with pytest.raises(GymError) as error:
            remove(user, plan.public_id, plan.revision)
        assert error.value.status == 409
        db.session.rollback()
    else:
        assert remove(user, plan.public_id, plan.revision)
        db.session.commit()
        assert plan.deleted_at is not None
    assert db.session.query(PlannedWorkout).filter_by(id=row.id).count() == 1
    if status == 'skipped':
        from app.services.mobile_sync import MobileSyncError
        with pytest.raises(MobileSyncError):
            PlannedWorkoutService.transition(row, 'planned', base_revision=row.revision, device_id=None)


def test_draft_version_only_reference_and_foreign_owner_guard(app, user):
    plan = program(user)
    version = get_active_version(plan, user)
    row = WorkoutSessionDraft(user_id=user, training_plan_id=None, training_plan_version_id=version.id,
        client_submission_id=str(uuid.uuid4()), payload_json={}, payload_hash='0'*64,
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    db.session.add(row)
    db.session.commit()
    with pytest.raises(GymError, match='borrador'):
        remove(user, plan.public_id, plan.revision)
    db.session.rollback()
    other = User(username='foreign-qa', role='user')
    other.set_password('fictional-password')
    db.session.add(other)
    db.session.flush()
    row.user_id = other.id  # Deliberately inconsistent fixture: never cascade foreign rows.
    db.session.commit()
    with pytest.raises(GymError, match='referencias'):
        remove(user, plan.public_id, plan.revision)
    db.session.rollback()
    assert db.session.query(WorkoutSessionDraft).count() == 1


def test_owner_revision_confirmation_and_atomic_rollback(app, user, monkeypatch):
    plan = program(user)
    public_id, revision = plan.public_id, plan.revision
    other = User(username='delete-other-qa', role='user')
    other.set_password('fictional-password')
    db.session.add(other)
    db.session.commit()
    for owner, pid, rev, confirmation, expected in [
        (other.id, public_id, revision, 'ELIMINAR', 404),
        (user, str(uuid.uuid4()), revision, 'ELIMINAR', 404),
        (user, public_id, revision + 1, 'ELIMINAR', 409),
        (user, public_id, revision, '', 400),
    ]:
        with pytest.raises(GymError) as error:
            delete_program(owner, pid, base_revision=rev, confirmation=confirmation)
        assert error.value.status == expected
        db.session.rollback()
    def fail(**kwargs):
        raise RuntimeError('QA injected failure after DELETE')
    with monkeypatch.context() as patch:
        patch.setattr('app.services.gym_delete.record_sync_change', fail)
        with pytest.raises(RuntimeError):
            remove(user, public_id, revision)
        db.session.rollback()
    assert db.session.query(TrainingPlan).filter_by(public_id=public_id).count() == 1
    assert db.session.query(TrainingPlanVersion).count() == 1
    remove(user, public_id, revision)
    db.session.commit()
    with pytest.raises(GymError) as error:
        remove(other.id, public_id, revision)
    assert error.value.status == 404


def test_web_csrf_confirmation_and_dashboard_ai_regression(app, client, user):
    plan = program(user)
    public_id, revision = plan.public_id, plan.revision
    url = f'/gym/programs/{public_id}/delete'
    assert client.get(url).status_code == 302
    login(client)
    app.config['WTF_CSRF_ENABLED'] = True
    page = client.get(url)
    assert page.status_code == 200
    assert db.session.query(TrainingPlan).count() == 1  # GET never writes.
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    form = {'base_revision': revision, 'confirmation': 'ELIMINAR'}
    assert client.post(url, data=form).status_code == 400
    assert client.post(url, data=form | {'csrf_token':token, 'confirmation':'no'}).status_code == 400
    assert client.post(url, data=form | {'csrf_token':token}).status_code == 303
    assert client.post(url, data=form | {'csrf_token':token}).status_code == 303
    assert read_program(user) == {'status':'no_active_program', 'days':[]}
    for path in ('/dashboard', '/training-plans', '/training-sessions', '/gym', '/ai'):
        assert client.get(path, follow_redirects=True).status_code == 200, path


def test_web_rejects_foreign_owner_and_stale_revision(app, client, user):
    other = User(username='foreign-web-qa', role='user')
    other.set_password('fictional-password')
    db.session.add(other)
    db.session.commit()
    foreign = program(other.id)
    local = program(user)
    login(client)
    url = f'/gym/programs/{foreign.public_id}/delete'
    assert client.get(url).status_code == 404
    assert client.post(url, data={'user_id':other.id, 'base_revision':foreign.revision, 'confirmation':'ELIMINAR'}).status_code == 404
    url = f'/gym/programs/{local.public_id}/delete'
    assert client.post(url, data={'base_revision':local.revision+1, 'confirmation':'ELIMINAR'}).status_code == 409
    assert db.session.query(TrainingPlan).count() == 2


def _csrf_token(page):
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)


def test_pending_draft_blocker_can_be_reviewed_and_discarded_individually(
    app, client, user
):
    plan = program(user)
    version = get_active_version(plan, user)
    draft = WorkoutSessionDraft(
        user_id=user,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        client_submission_id=str(uuid.uuid4()),
        payload_json={"fictional": "pending draft"},
        payload_hash="0" * 64,
        expires_at=datetime.now(timezone.utc),
    )
    db.session.add(draft)
    db.session.commit()
    draft_id = draft.public_id
    with pytest.raises(GymError, match="borradores"):
        remove(user, plan.public_id, plan.revision)
    db.session.rollback()

    login(client)
    app.config["WTF_CSRF_ENABLED"] = True
    pending_url = f"/gym/programs/{plan.public_id}/pending"
    page = client.get(pending_url)
    assert page.status_code == 200
    assert "Borradores de sesión" in page.text
    token = _csrf_token(page)
    discard_url = f"{pending_url}/draft/{draft_id}/discard"
    rejected = client.post(
        discard_url,
        data={"csrf_token": token, "confirmation": "NO"},
    )
    assert rejected.status_code == 400
    assert db.session.get(WorkoutSessionDraft, draft.id) is not None
    discarded = client.post(
        discard_url,
        data={"csrf_token": token, "confirmation": "DESCARTAR"},
    )
    assert discarded.status_code == 303
    assert db.session.get(WorkoutSessionDraft, draft.id) is None
    assert client.post(
        f"/gym/programs/{plan.public_id}/delete",
        data={
            "csrf_token": token,
            "base_revision": plan.revision,
            "confirmation": "ELIMINAR",
        },
    ).status_code == 303


def test_pending_session_and_agenda_are_resolved_individually_with_confirmation(
    app, client, user
):
    plan = program(user)
    session = start(user, plan)
    complete_set(
        user,
        session.public_id,
        1,
        1,
        {"load": "35", "unit": "kg", "reps": "8", "rir": "2"},
    )
    agenda = PlannedWorkoutService.schedule_from_plan_version(
        user_id=user,
        plan_public_id=plan.public_id,
        version_public_id=None,
        scheduled_for_date=date(2026, 9, 18),
        timezone_name="UTC",
        week_number=1,
        day_number=1,
    )
    db.session.commit()
    session_id, agenda_id, plan_id, plan_revision = (
        session.public_id,
        agenda.public_id,
        plan.id,
        plan.revision,
    )
    with pytest.raises(GymError, match="sesión pendiente"):
        remove(user, plan.public_id, plan.revision)
    db.session.rollback()

    login(client)
    app.config["WTF_CSRF_ENABLED"] = True
    pending_url = f"/gym/programs/{plan.public_id}/pending"
    page = client.get(pending_url)
    token = _csrf_token(page)
    assert session_id in page.text and agenda_id in page.text

    discard_session_url = f"{pending_url}/session/{session_id}/discard"
    rejected = client.post(
        discard_session_url,
        data={"csrf_token": token, "confirmation": "NO"},
    )
    assert rejected.status_code == 400
    assert db.session.query(TrainingSession).filter_by(public_id=session_id).one()
    assert db.session.query(TrainingSet).count() == 1
    assert client.post(
        discard_session_url,
        data={"csrf_token": token, "confirmation": "DESCARTAR"},
    ).status_code == 303
    assert db.session.query(TrainingSession).filter_by(public_id=session_id).one_or_none() is None
    assert db.session.query(TrainingSet).count() == 0

    discard_agenda_url = f"{pending_url}/planned/{agenda_id}/discard"
    assert client.post(
        discard_agenda_url,
        data={"csrf_token": token, "confirmation": "DESCARTAR"},
    ).status_code == 303
    agenda_row = db.session.query(PlannedWorkout).filter_by(public_id=agenda_id).one()
    assert agenda_row.deleted_at is not None and agenda_row.status == "cancelled"
    page = client.get(pending_url)
    assert "No quedan pendientes" in page.text
    response = client.post(
        f"/gym/programs/{plan.public_id}/delete",
        data={
            "csrf_token": token,
            "base_revision": plan_revision,
            "confirmation": "ELIMINAR",
        },
    )
    assert response.status_code == 303, response.text
    assert db.session.get(TrainingPlan, plan_id).deleted_at is not None


def test_mobile_tombstone_and_no_resurrection(app, client, user):
    plan = program(user)
    public_id, revision = plan.public_id, plan.revision
    token = _api_login(client)['access_token']
    headers = _auth(token)
    bootstrap = client.get('/api/v1/sync/bootstrap', headers=headers).get_json()['data']
    remove(user, public_id, revision)
    db.session.commit()
    changes = client.get(f"/api/v1/sync/pull?cursor={bootstrap['cursor']}&entity_types=training_plan", headers=headers)
    assert changes.status_code == 200
    tombstone = changes.get_json()['data']['changes'][-1]
    assert tombstone['operation'] == 'delete' and tombstone['payload'] is None
    assert client.get(f'/api/v1/mobile/plans/{public_id}', headers=headers).status_code == 404
    assert _create_plan(client, token, public_id=public_id).status_code == 409
    fresh = _create_plan(client, token, key='fresh-qa')
    assert fresh.status_code == 201
    source_id = fresh.get_json()['data']['public_id']
    assert client.post(f'/api/v1/mobile/plans/{source_id}/duplicate', json={'public_id':public_id},
                       headers=_headers(token, 'duplicate-deleted-qa')).status_code == 409


def test_removed_history_is_immutable_and_absent_from_all_planning(app, client, user):
    from app.services.exporters.training_session import build_completed_workout_document
    from app.services.workout_sessions import list_planned_days, resolve_planned_day, TrainingSessionError
    from app.services.mobile_planning import list_plans, patch_plan
    from app.services.mobile_sync import MobileSyncError
    plan = program(user)
    row = start(user, plan)
    complete_set(user, row.public_id, 1, 1, {'load':'42.5','unit':'kg','reps':'7','rir':'2'})
    finish_session(user, row.public_id, 'completed')
    db.session.commit()
    snapshot = build_completed_workout_document(row, user)
    public_id, revision, plan_id = plan.public_id, plan.revision, plan.id
    key = f'{row.training_plan_version_id}:0:0'
    assert remove(user, public_id, revision)
    db.session.commit()
    assert build_completed_workout_document(row, user) == snapshot
    assert list_planned_days(user) == [] and list_plans(user_id=user) == []
    assert read_program(user)['status'] == 'no_active_program'
    assert read_session(user, row.public_id)['session_id'] == row.public_id
    with pytest.raises(TrainingSessionError):
        resolve_planned_day(key, user)
    with pytest.raises(MobileSyncError):
        patch_plan(user_id=user, public_id=public_id, payload={'base_revision':revision+1, 'status':'active'}, device_id=None)
    login(client)
    assert public_id not in client.get('/training-plans').text
    from app.planned.routes import _options
    assert _options(user) == []
    for route in (f'/training-plans/{plan_id}', f'/gym/programs/{public_id}/edit', f'/gym/programs/{public_id}/delete'):
        assert client.get(route).status_code == 404
    for route in ('/dashboard', '/ai', '/training-sessions', f'/training-sessions/{row.id}'):
        assert client.get(route).status_code == 200
    assert snapshot == build_completed_workout_document(row, user)


def test_deleted_history_survives_account_restore_without_resurrection(app, user):
    from app.services.exporters.user_data import build_user_data_document
    from tests.test_account_restore import _restore_payload_to_user
    plan = program(user)
    row = start(user, plan)
    complete_set(user, row.public_id, 1, 1, {'load':'42','unit':'kg','reps':'7','rir':'2'})
    finish_session(user, row.public_id, 'completed')
    db.session.commit()
    remove(user, plan.public_id, plan.revision)
    db.session.commit()
    payload = build_user_data_document(db.session.get(User, user), user)
    target = User(username='restore-deleted-qa', role='user')
    target.set_password('fictional-only')
    db.session.add(target)
    db.session.commit()
    _restore_payload_to_user(payload, target.id)
    restored = db.session.query(TrainingPlan).filter_by(user_id=target.id).one()
    assert restored.deleted_at is not None and not restored.gym_active
    assert db.session.query(TrainingSession).filter_by(user_id=target.id).count() == 1
    assert db.session.query(TrainingSet).filter_by(user_id=target.id).one().weight_kg == 42


def test_deleted_history_portable_roundtrip_and_mobile_tombstone(app, client, user):
    from tests.test_data_portability import _export, _package, _inspect, _second_user, _headers
    plan = program(user)
    row = start(user, plan)
    complete_set(user, row.public_id, 1, 1, {'load':'42','unit':'kg','reps':'7','rir':'2'})
    finish_session(user, row.public_id, 'completed')
    db.session.commit()
    token = _api_login(client)['access_token']
    cursor = client.get('/api/v1/sync/bootstrap', headers=_auth(token)).get_json()['data']['cursor']
    public_id = plan.public_id
    remove(user, public_id, plan.revision)
    db.session.commit()
    changes = client.get(f'/api/v1/sync/pull?cursor={cursor}&entity_types=training_plan', headers=_auth(token)).get_json()['data']['changes']
    assert changes[-1]['operation'] == 'delete' and changes[-1]['payload'] is None
    assert client.get(f'/api/v1/mobile/plans/{public_id}', headers=_auth(token)).status_code == 404
    sections = ['plans','sessions','session_exercises','sets']
    exported = _export(client, token, key='deleted-history', sections=sections)
    assert exported.status_code == 201
    content = _package(client, token, exported.get_json()['data']['export_id'])
    target, target_token = _second_user(app, client)
    preview = _inspect(client, target_token, content, sections=sections)
    assert preview.status_code == 201
    job = preview.get_json()['data']
    response = client.post(f"/api/v1/mobile/portability/imports/{job['import_id']}/apply",
        json={'confirmed':True,'plan_revision':1,'decisions':[]}, headers=_headers(target_token,'deleted-restore'))
    assert response.status_code == 200, response.get_json()
    restored = db.session.query(TrainingPlan).filter_by(user_id=target).one()
    assert restored.deleted_at is not None and not restored.gym_active
    assert db.session.query(TrainingSession).filter_by(user_id=target).count() == 1
    assert db.session.query(TrainingSet).filter_by(user_id=target).one().weight_kg == 42
