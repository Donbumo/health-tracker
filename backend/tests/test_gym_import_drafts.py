"""Fictional fixtures: upload expiry must never discard interactive work."""
import copy
import hashlib
import io
import json
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.extensions import db
from app.models import GymImportDraft, Exercise, ExerciseAlias, TrainingPlan, TrainingPlanVersion, User, ImportRun, UploadedFile
from app.services import gym_import_drafts as drafts
from app.services.exercise_catalog import sync_catalog, external_catalog
from app.services.gym_programs import GymError
from tests.conftest import login
from tests.test_external_exercise_catalog import app, FixtureSource, sample

RAW = ('Day,Exercise,Sets,Reps,Load,RIR,Rest\n' + ''.join(f'QA day,QA unknown {i},2,6-8,20kg,2,90\n' for i in range(6))).encode()


@pytest.fixture
def refs(app):
    sync_catalog(source=FixtureSource(entries=[sample('QA_'+str(i), 'QA reference '+str(i)) for i in range(6)]))
    return [row.public_id for row in external_catalog()]


def upload(client):
    login(client)
    response = client.post('/gym/programs/new', data={'name':'QA durable routine','file':(io.BytesIO(RAW),'qa.csv')})
    assert response.status_code == 302
    return response.location.rsplit('/', 1)[-1]


def save(client, key, revision, index, value):
    return client.post(f'/gym/programs/drafts/{key}/save', json={'revision':revision,'change':{'action':'mapping','day':0,'exercise':index,'value':value}})


def confirm(client, key, state):
    return client.post('/gym/programs/confirm', data={'draft_id':key,'revision':state['revision'],'token':state['token']})


def test_expired_physically_absent_original_refresh_reopen_confirm(app, client, user, refs, tmp_path):
    original = tmp_path/'qa-original.csv'
    original.write_bytes(RAW)
    key = upload(client)
    row = drafts.owned(user, key)
    before = copy.deepcopy(row.payload_json['days'][0]['exercises'][0]['sets'])
    for i in range(3):
        response = save(client,key,i+1,i,'catalog:'+refs[i]); assert response.status_code == 200
    original.unlink()
    # Neither file retention nor the age of the original/draft gates confirmation.
    row = drafts.owned(user,key); row.created_at = datetime.now(timezone.utc)-timedelta(days=60); db.session.commit()
    assert not original.exists()
    assert not list(app.config['UPLOAD_ROOT'].rglob('.gym-preview-*.tmp'))
    assert db.session.query(Exercise).filter_by(user_id=user).count() == 0
    assert db.session.query(ExerciseAlias).filter_by(user_id=user).count() == 0
    reopened = app.test_client(); login(reopened)
    assert 'Continuar importación' in reopened.get('/training-plans').text
    page = reopened.get('/gym/programs/drafts/'+key)
    assert page.status_code == 200
    for ref in refs[:3]: assert f'value="catalog:{ref}" selected' in page.text
    for i in range(3,6):
        response = save(reopened,key,i+1,i,'catalog:'+refs[i]); assert response.status_code == 200
    state = response.json
    assert state['ready'] and confirm(reopened,key,state).status_code == 302
    assert confirm(reopened,key,state).status_code == 302  # Lost HTTP response retry.
    assert db.session.query(TrainingPlan).filter_by(user_id=user).count() == 1
    assert db.session.query(ImportRun).filter_by(user_id=user).count() == 1
    assert db.session.query(UploadedFile).filter_by(user_id=user).count() == 0
    assert db.session.query(ImportRun).one().payload_sha256 == hashlib.sha256(RAW).hexdigest()
    assert db.session.query(ExerciseAlias).filter_by(user_id=user).count() == 6
    document = db.session.query(TrainingPlanVersion).one().content
    actual = document['data']['weeks'][0]['days'][0]['exercises'][0]['sets']
    for old,new in zip(before,actual):
        for key,value in old.items(): assert str(new[key]) == str(value)
    assert db.session.query(GymImportDraft).one().state == 'completed'


def test_stale_tab_does_not_overwrite_saved_mapping(app,client,user,refs):
    key=upload(client)
    state=save(client,key,1,0,'catalog:'+refs[0]).json
    response=save(client,key,1,0,'catalog:'+refs[1])
    assert response.status_code==409 and response.json['error']==drafts.STALE
    row=drafts.owned(user,key)
    assert row.payload_json['days'][0]['exercises'][0]['resolved_catalog_id']==refs[0]
    assert confirm(client,key,dict(state,revision=1)).status_code==409


def test_none_new_unresolved_and_changed_mapping_remain_draft_only(app,client,user,refs):
    key=upload(client)
    values=['catalog:'+refs[0], 'catalog:'+refs[1], 'none', '', 'new']
    for revision,value in enumerate(values,1):
        response=save(client,key,revision,0,value);assert response.status_code==200
        row=drafts.owned(user,key);ex=row.payload_json['days'][0]['exercises'][0]
        if value=='none': assert ex['mapping_choice']=='none' and 'resolved_catalog_id' not in ex
        if value=='': assert ex['mapping_choice']=='unresolved' and not response.json['ready']
    assert db.session.query(Exercise).count()==0
    assert confirm(client,key,response.json).status_code==400
    assert drafts.owned(user,key).state=='pending'


def test_cancel_does_not_publish_and_rejects_confirm(app,client,user,refs):
    key=upload(client);state=save(client,key,1,0,'catalog:'+refs[0]).json
    assert client.post(f'/gym/programs/drafts/{key}/cancel',data={'revision':state['revision']}).status_code==302
    assert drafts.owned(user,key).payload_json=={}
    assert drafts.owned(user,key).state=='cancelled'
    assert confirm(client,key,state).status_code==409
    assert not drafts.pending(user)
    assert db.session.query(Exercise).count()==db.session.query(TrainingPlan).count()==0
    assert not list(app.config['UPLOAD_ROOT'].rglob('.gym-preview-*.tmp'))


def test_owner_isolation_and_csrf(app,client,user,refs):
    from flask import g
    key=upload(client);state=drafts.status(drafts.owned(user,key))
    other=User(username='QA-other-draft',role='user');other.set_password('fictional-password');db.session.add(other);db.session.commit()
    g.pop('_login_user', None)
    theirs=app.test_client();login(theirs,'QA-other-draft','fictional-password')
    assert theirs.get('/gym/programs/drafts/'+key).status_code==404
    assert save(theirs,key,1,0,'new').status_code==404
    assert confirm(theirs,key,state).status_code==404
    assert theirs.post(f'/gym/programs/drafts/{key}/cancel',data={'revision':1}).status_code==404
    assert key not in theirs.get('/training-plans').text
    g.pop('_login_user', None)
    assert app.test_client().get('/gym/programs/drafts/'+key).status_code==302
    g.pop('_login_user', None)
    app.config['WTF_CSRF_ENABLED']=True
    assert save(client,key,1,0,'new').status_code==403
    assert confirm(client,key,state).status_code==400


def test_manual_corrections_autosave_survive_incomplete_editor(app,client,user,refs):
    key=upload(client);row=drafts.owned(user,key)
    payload={'program':copy.deepcopy(row.payload_json['program']),'days':copy.deepcopy(row.payload_json['days'])}
    payload['program']['name']=''
    response=client.post(f'/gym/programs/drafts/{key}/save',json={'revision':1,'change':{'action':'edit','draft':payload}})
    assert response.status_code==200 and not response.json['ready']
    assert client.get('/gym/programs/drafts/'+key).status_code==200
    payload['program']['name']='QA corrected durable routine';payload['days'][0]['exercises'][0]['sets'][0]['reps_min']=7
    response=client.post(f'/gym/programs/drafts/{key}/save',json={'revision':2,'change':{'action':'edit','draft':payload}})
    assert response.status_code==200
    stored=drafts.owned(user,key).payload_json
    assert stored['program']['name']==payload['program']['name'] and stored['days'][0]['exercises'][0]['sets'][0]['reps_min']==7
    assert stored['source_sha256']==hashlib.sha256(RAW).hexdigest()


def test_field_allowlist_limits_and_foreign_identity(app,client,user,refs):
    key=upload(client);row=drafts.owned(user,key)
    payload={'program':row.payload_json['program'],'days':row.payload_json['days'],'user_id':999}
    assert client.post(f'/gym/programs/drafts/{key}/save',json={'revision':1,'change':{'action':'edit','draft':payload}}).status_code==400
    assert save(client,key,1,-1,'new').status_code==400
    assert save(client,key,1,0,'not-an-owner-identity').status_code==404
    assert drafts.owned(user,key).revision==1


def test_confirmation_uses_only_server_draft_and_rejects_tampered_token(app,client,user,refs):
    key=upload(client)
    for i in range(6): state=save(client,key,i+1,i,'new').json
    assert confirm(client,key,dict(state,token='tampered')).status_code==409
    response=client.post('/gym/programs/confirm',data={'draft_id':key,'revision':state['revision'],'token':state['token'],'draft':'{"user_id":999,"days":[]}','plan_id':'foreign'})
    assert response.status_code==302
    assert db.session.query(TrainingPlan).one().name=='QA durable routine'


def test_confirm_failure_is_atomic_and_preserves_draft(app,client,user,refs,monkeypatch):
    key=upload(client)
    for i in range(6): state=save(client,key,i+1,i,'catalog:'+refs[i]).json
    from app.services import gym_programs
    def fail(*args,**kwargs): raise GymError('QA injected publication failure')
    monkeypatch.setattr(gym_programs,'publish_program_document',fail)
    assert confirm(client,key,state).status_code==400
    assert drafts.owned(user,key).state=='pending'
    assert db.session.query(Exercise).count()==db.session.query(ExerciseAlias).count()==0


def test_program_update_preserves_history_and_rejects_stale_target(app,client,user):
    from tests.test_gym_training import program, start
    from app.services.gym_sessions import complete_set
    from app.services.training_plans import get_active_version
    from app.services.importers.routine_draft import draft_from_document
    plan=program(user);session=start(user,plan)
    complete_set(user,session.public_id,1,1,{'load':'20','unit':'kg','reps':'8','rir':'2'});db.session.commit()
    previous=get_active_version(plan,user);content=copy.deepcopy(previous.content)
    first=draft_from_document(content);first.program['name']='QA updated routine'
    second=copy.deepcopy(first);second.program['name']='QA stale alternative'
    a=drafts.create(first,user,plan=plan,base_revision=plan.revision)
    b=drafts.create(second,user,plan=plan,base_revision=plan.revision);db.session.commit()
    a_id,b_id=a.public_id,b.public_id;a_state,b_state=drafts.status(a),drafts.status(b)
    login(client)
    assert confirm(client,a_id,a_state).status_code==302
    assert confirm(client,b_id,b_state).status_code==409
    db.session.refresh(previous);db.session.refresh(session)
    assert previous.content==content and session.training_plan_version_id==previous.id
    from app.models import TrainingSet
    assert db.session.query(TrainingSet).filter_by(user_id=user).count()==1
    assert drafts.owned(user,b_id).state=='pending'


def test_no_js_mapping_form_and_signed_confirmation_without_short_ttl(app,client,user,monkeypatch):
    key=upload(client)
    data={'revision':1,**{f'mapping_0_{i}':'new' for i in range(6)}}
    assert client.post(f'/gym/programs/drafts/{key}/review',data=data).status_code==302
    state=drafts.status(drafts.owned(user,key))
    # Persisted decisions are bounded by owner/state/revision, not upload age.
    import time
    now=time.time();monkeypatch.setattr(time,'time',lambda:now+60*86400)
    assert confirm(client,key,state).status_code==302


@pytest.mark.skipif(not os.environ.get('CATALOG_TEST_MARIADB'), reason='Isolated MariaDB concurrency gate')
def test_mariadb_concurrent_autosave_and_double_confirm(app,client,user,refs):
    key=upload(client)
    barrier=Barrier(2)
    def update(value):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                row=drafts.save(user,key,1,{'action':'mapping','day':0,'exercise':0,'value':value});db.session.commit();return 200
            except GymError as error:
                db.session.rollback();return error.status
    db.session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(update,['new','none']))
    assert sorted(results)==[200,409]
    from flask import g
    g.pop('_login_user', None)
    for i in range(1,6): state=save(client,key,i+1,i,'new').json
    db.session.remove();barrier=Barrier(2)
    def commit(_):
        with app.app_context():
            barrier.wait(timeout=10)
            plan,duplicate=drafts.confirm(user,key,state['revision'],state['token']);db.session.commit();return plan.public_id,duplicate
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(commit,range(2)))
    assert results[0][0]==results[1][0] and sorted(r[1] for r in results)==[False,True]
    assert db.session.query(TrainingPlan).filter_by(user_id=user).count()==1
