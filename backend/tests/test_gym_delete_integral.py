"""Real-route gate shared by SQLite and the disposable MariaDB suite."""
import re
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from app.extensions import db
from app.models import (PlannedWorkout, TrainingPlan, TrainingSession, TrainingSet,
                        WorkoutSessionDraft, SyncChange, User)
from app.services.gym_programs import preset_draft
from app.services.gym_sessions import complete_set, finish_session
from app.services.mobile_sync import PlannedWorkoutService, MobileSyncError
from app.services.exporters.training_session import build_completed_workout_document
from tests.test_gym_training import program, start


def seed(owner, *, partial=False, name="QA eliminaciÃ³n integral"):
    draft = preset_draft('full-body-v1')
    draft.program['name'] = name
    plan = program(owner, draft)
    history = start(owner, plan)
    complete_set(owner, history.public_id, 1, 1, {'load':'42.5','unit':'kg','reps':'7','rir':'2'})
    finish_session(owner, history.public_id, 'completed')
    db.session.commit()
    snapshot = build_completed_workout_document(history, owner)
    session = start(owner, plan)
    if partial:
        complete_set(owner, session.public_id, 1, 1, {'load':'30','unit':'kg','reps':'6','rir':'3'})
    agenda = PlannedWorkoutService.schedule_from_plan_version(
        user_id=owner, plan_public_id=plan.public_id, version_public_id=None,
        scheduled_for_date=date(2026, 9, 24), timezone_name='UTC', week_number=1, day_number=1)
    session.planned_workout_id = agenda.id
    agenda.status = 'in_progress'
    draft = WorkoutSessionDraft(user_id=owner, training_plan_id=plan.id,
        training_plan_version_id=session.training_plan_version_id,
        client_submission_id=str(uuid.uuid4()), payload_json={'fictional':'QA draft'},
        payload_hash='0'*64, expires_at=datetime.now(timezone.utc))
    db.session.add(draft)
    db.session.commit()
    return plan, session, agenda, draft, history, snapshot


def authenticate(client, owner):
    from flask import g
    g.pop('_login_user', None)
    with client.session_transaction() as cookie:
        cookie['_user_id'] = str(owner)
        cookie['_fresh'] = True


def form_for(client, plan):
    page = client.get(f'/gym/programs/{plan.public_id}/delete')
    assert page.status_code == 200
    assert '<dialog ' in page.text and 'Revisar pendientes' not in page.text
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)"', page.text))
    return fields | {'confirmation':'ELIMINAR'}


def integral_gate(application, owner, *, partial=False, action=None, rollback_patch=None):
    application.config['WTF_CSRF_ENABLED'] = True
    client = application.test_client()
    authenticate(client, owner)
    plan, session, agenda, draft, history, snapshot = seed(owner, partial=partial)
    plan_id, sid, did, aid, hid = plan.id, session.id, draft.id, agenda.id, history.id
    pid = plan.public_id
    url = f'/gym/programs/{pid}/delete'
    assert f'href="{url}"' in client.get('/training-plans').text
    form = form_for(client, plan)
    if partial:
        assert 'Series parciales registradas: 1' in client.get(url).text
        assert client.post(url, data=form).status_code == 400
        assert client.post(url, data=form | {'partial_action':'discard'}).status_code == 400
        form |= {'partial_action':action, 'partial_confirmation':'DESCARTAR' if action == 'discard' else ''}
    assert client.post(url, data={key:value for key,value in form.items() if key != 'csrf_token'}).status_code == 400
    if rollback_patch:
        with rollback_patch.context() as patch:
            def fail(**kwargs):
                raise RuntimeError('QA failure after pending cleanup')
            patch.setattr('app.services.gym_delete.record_sync_change', fail)
            with pytest.raises(RuntimeError):
                client.post(url, data=form)
        db.session.expire_all()
        assert db.session.get(TrainingPlan, plan_id).deleted_at is None
        assert db.session.get(WorkoutSessionDraft, did) is not None
        assert db.session.get(TrainingSession, sid).status == 'in_progress'
        assert db.session.get(PlannedWorkout, aid).deleted_at is None
    response = client.post(url, data=form)
    assert response.status_code == 303, response.text
    assert client.post(url, data=form).status_code == 303
    db.session.expire_all()
    assert db.session.get(TrainingPlan, plan_id).deleted_at is not None
    assert db.session.get(WorkoutSessionDraft, did) is None
    if partial and action == 'preserve':
        assert db.session.get(TrainingSession, sid).status == 'abandoned'
        assert db.session.get(TrainingSession, sid).planned_workout_id == aid
        assert db.session.query(TrainingSet).filter_by(user_id=owner).count() == 2
    else:
        assert db.session.get(TrainingSession, sid) is None
        assert db.session.query(TrainingSet).filter_by(user_id=owner).count() == 1
    saved = db.session.get(TrainingSession, hid)
    assert build_completed_workout_document(saved, owner) == snapshot
    assert saved.training_plan is not None and saved.training_plan_version is not None
    cancelled = db.session.get(PlannedWorkout, aid)
    assert cancelled.deleted_at is not None and cancelled.status == 'cancelled'
    assert not PlannedWorkoutService.list_range(owner, date(2026,9,24), date(2026,9,24))
    for status in ('planned','in_progress'):
        with pytest.raises(MobileSyncError):
            PlannedWorkoutService.transition(cancelled, status, base_revision=cancelled.revision, device_id=None)
        db.session.rollback()
    assert db.session.query(SyncChange).filter_by(user_id=owner, entity_public_id=pid, operation='delete').count() == 1
    assert db.session.query(SyncChange).filter_by(user_id=owner, entity_public_id=cancelled.public_id, operation='delete').count() == 1
    assert client.get(url).status_code == 404
    for path in ('/dashboard','/training-plans','/training-sessions','/ai'):
        assert client.get(path).status_code == 200


@pytest.mark.parametrize('action', [None, 'preserve', 'discard'])
def test_integral_real_route(app, user, monkeypatch, action):
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    db.session.commit()
    integral_gate(app, user, partial=action is not None, action=action, rollback_patch=monkeypatch)


def test_stale_confirmation_and_owner_isolation(app, user):
    client = app.test_client()
    authenticate(client, user)
    plan, session, agenda, draft, history, snapshot = seed(user)
    form = form_for(client, plan)
    complete_set(user, session.public_id, 1, 1, {'load':'30','unit':'kg','reps':'6','rir':'3'})
    db.session.commit()
    url = f'/gym/programs/{plan.public_id}/delete'
    assert client.post(url, data=form).status_code == 409
    assert db.session.get(WorkoutSessionDraft, draft.id) is not None
    other = User(username='QA foreign integral', role='user')
    other.set_password('fictional-only-password')
    db.session.add(other)
    db.session.commit()
    foreign = program(other.id)
    own_other = program(user, preset_draft('upper-lower-v1'))
    original = foreign.public_id
    authenticate(client, other.id)
    assert client.get(url).status_code == 404
    assert client.get(f'/gym/programs/{plan.public_id}/pending').status_code == 404
    assert client.post(url, data=form | {'user_id':user}).status_code == 404
    assert client.post(f'/gym/programs/{plan.public_id}/pending/session/{session.public_id}/discard', data={'confirmation':'DESCARTAR'}).status_code == 404
    authenticate(client, user)
    # A valid confirmation is tied to its owner and its exact routine.
    assert client.post(f'/gym/programs/{own_other.public_id}/delete', data=form).status_code == 409
    assert client.post(f'/gym/programs/{own_other.public_id}/pending/draft/{draft.public_id}/discard', data={'confirmation':'DESCARTAR'}).status_code == 404
    assert db.session.query(TrainingPlan).filter_by(public_id=original).one().deleted_at is None
    assert db.session.get(TrainingSession, history.id).status == 'completed'


def test_individual_csrf_and_no_collateral_changes(app, user):
    app.config['WTF_CSRF_ENABLED'] = True
    client = app.test_client()
    authenticate(client, user)
    plan, session, agenda, draft, history, snapshot = seed(user, partial=True)
    unrelated = program(user, preset_draft('upper-lower-v1'))
    unrelated_id = unrelated.id
    token = form_for(client, plan)['csrf_token']
    pending = f'/gym/programs/{plan.public_id}/pending'
    for kind, item in [('draft', draft), ('session', session), ('planned', agenda)]:
        url = f'{pending}/{kind}/{item.public_id}/discard'
        assert client.post(url, data={'confirmation':'DESCARTAR'}).status_code == 400
        assert client.post(url, data={'csrf_token':token, 'confirmation':'NO'}).status_code == 400
        assert client.post(url, data={'csrf_token':token, 'confirmation':'DESCARTAR'}).status_code == 303
        assert db.session.get(TrainingPlan, unrelated_id).deleted_at is None
        assert db.session.get(TrainingPlan, plan.id).deleted_at is None
    assert build_completed_workout_document(history, user) == snapshot
    assert 'No quedan pendientes' in client.get(pending).text


def test_signed_inventory_cannot_be_tampered_with(app, user):
    client = app.test_client()
    authenticate(client, user)
    plan, session, agenda, draft, _, _ = seed(user)
    form = form_for(client, plan)
    form['pending_token'] = form['pending_token'][:-8] + 'tampered'
    response = client.post(f'/gym/programs/{plan.public_id}/delete', data=form)
    assert response.status_code == 409
    assert db.session.get(WorkoutSessionDraft, draft.id) is not None
    assert db.session.get(TrainingSession, session.id) is not None
    assert db.session.get(PlannedWorkout, agenda.id).deleted_at is None
