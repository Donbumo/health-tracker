"""Fictional C HTTP flow: no writes before confirmation, no new domain writer."""
import base64
import copy
import hashlib
import html
import io
import json
import re

import pytest
from itsdangerous.timed import TimestampSigner

from app.extensions import db
from app.models import DailyEnergy, EnergyDay, EnergyEvidenceEvent, UploadedFile, User
from app.services import energy_days as energy
from app.services import energy_guided as guided
from app.services.importers.standard_import_executor import StandardImportExecutor
from tests.conftest import login
from tests.test_energy_days import document, DAY


def hidden(response):
    fields = {}
    for tag in re.findall(r'<input\b[^>]*>', response.get_data(as_text=True)):
        attrs = dict((k, html.unescape(v)) for k,v in re.findall(r'([\w_-]+)="([^"]*)"', tag))
        if attrs.get('type') == 'hidden':
            fields[attrs['name']] = attrs.get('value','')
    return fields


def upload(client, doc, raw=None):
    raw = raw if raw is not None else json.dumps(doc).encode()
    return client.post('/energy/import',data={'action':'upload','file':(io.BytesIO(raw),'QA-C-energy.json')})


def advance(client, response, action, path='/energy/import', **extras):
    return client.post(path,data={**hidden(response),'action':action,**extras})


def final_import(client, doc, raw=None):
    response = upload(client,doc,raw)
    for action in ('review','approve'):
        assert response.status_code==200, response.get_data(as_text=True)
        response = advance(client,response,action)
    assert response.status_code==200
    return response


def counts():
    return [db.session.query(model).count() for model in (DailyEnergy,EnergyDay,EnergyEvidenceEvent,UploadedFile)]


def test_four_steps_readonly_original_exact_and_idempotent(app,client,user):
    login(client);doc=document(user,'QA C partial',steps=0)
    raw=b'\xef\xbb\xbf'+json.dumps(doc,indent=2).encode()+b'\n\n'
    preview=upload(client,doc,raw);assert preview.status_code==200
    assert b'Observaci' in preview.data and b'parcial' in preview.data and b'Sin dato' in preview.data
    assert counts()==[0,0,0,0]
    review=advance(client,preview,'review');assert review.status_code==200 and counts()==[0,0,0,0]
    final=advance(client,review,'approve');assert final.status_code==200 and counts()==[0,0,0,0]
    assert b'PASO 4 DE 4' in final.data and b'Confirmaci' in final.data
    response=advance(client,final,'confirm',confirm='yes');assert response.status_code==302
    assert counts()==[1,1,1,1]
    day=energy.view(user,DAY);assert day.steps==0 and day.total_calories is None
    file=db.session.query(UploadedFile).one();assert file.sha256==hashlib.sha256(raw).hexdigest() and file.size_bytes==len(raw)
    event=db.session.query(EnergyEvidenceEvent).one();assert event.source_file_id==file.id
    previous=counts();revision=day.revision
    assert advance(client,final,'confirm',confirm='yes').status_code==302
    assert counts()==previous and energy.view(user,DAY).revision==revision
    again=final_import(client,doc,raw)
    assert advance(client,again,'confirm',confirm='yes').status_code==302
    assert counts()==previous and energy.view(user,DAY).revision==revision


@pytest.mark.parametrize('mutation',['raw','name','owner','step','missing_confirmation'])
def test_import_bound_to_original_owner_step_and_explicit_confirmation(app,client,user,mutation):
    login(client);doc=document(user,'QA C',total_expenditure_kcal=2000)
    final=final_import(client,doc);data={**hidden(final),'action':'confirm','confirm':'yes'}
    envelope=json.loads(data['envelope'])
    if mutation=='raw':envelope['raw']=base64.b64encode(json.dumps({**doc,'data':{**doc['data'],'steps':77}}).encode()).decode()
    if mutation=='name':envelope['name']='QA-changed.json'
    if mutation=='owner':
        other=User(username='QA C foreign',role='user');other.set_password('fictional-C');db.session.add(other);db.session.commit()
        changed=copy.deepcopy(doc);changed['user_id']=other.id;envelope['raw']=base64.b64encode(json.dumps(changed).encode()).decode()
    if mutation=='step':data['stage']='3'
    if mutation=='missing_confirmation':data.pop('confirm')
    data['envelope']=json.dumps(envelope)
    response=client.post('/energy/import',data=data)
    assert response.status_code in (400,409) and counts()==[0,0,0,0]


def test_import_stale_other_source_and_tombstone_do_not_write(app,client,user):
    login(client);doc=document(user,'QA C',steps=1);final=final_import(client,doc)
    energy.upsert_document(document(user,'QA new source',steps=20),user);db.session.commit();before=counts()
    assert advance(client,final,'confirm',confirm='yes').status_code==409
    assert counts()==before
    current=energy.view(user,DAY);energy.delete_day(user,DAY,current.revision);db.session.commit();before=counts()
    assert advance(client,final,'confirm',confirm='yes').status_code in (400,409)
    assert energy.view(user,DAY) is None and counts()==before


def test_file_commit_gap_rechecks_before_domain_write(app,client,user,monkeypatch):
    from app.wellness import guided_routes
    login(client);final=final_import(client,document(user,'QA C',steps=1));original=guided_routes.store_uploaded_file
    def intervening(file,owner):
        stored=original(file,owner)
        energy.upsert_document(document(owner,'QA concurrent writer',steps=80),owner);db.session.commit()
        return stored
    monkeypatch.setattr(guided_routes,'store_uploaded_file',intervening)
    assert advance(client,final,'confirm',confirm='yes').status_code==409
    assert db.session.query(DailyEnergy).one().source=='QA concurrent writer'
    assert db.session.query(UploadedFile).count()==1


def test_domain_failure_rolls_back_and_keeps_confirmed_original_for_audit(app,client,user,monkeypatch):
    login(client);final=final_import(client,document(user,'QA C',steps=1));original=StandardImportExecutor._apply_document
    def fail_after_flush(self,*args,**kwargs):
        original(self,*args,**kwargs);db.session.flush();raise RuntimeError('fictional QA injected failure')
    monkeypatch.setattr(StandardImportExecutor,'_apply_document',fail_after_flush)
    response=advance(client,final,'confirm',confirm='yes')
    assert response.status_code==409 and counts()==[0,0,0,1]


@pytest.mark.parametrize('raw',[b'{}',b'[]',b'null',b'{bad',b'\xff',b'X'*(guided.MAX_BYTES+1)],ids=['object','list','null','syntax','encoding','oversize'])
def test_invalid_uploads_cannot_create_records(app,client,user,raw):
    login(client);response=upload(client,{},raw)
    assert response.status_code==400 and counts()==[0,0,0,0]


def test_expiry_csrf_and_step_skip(app,client,user,monkeypatch):
    login(client);doc=document(user,'QA C',steps=0)
    with monkeypatch.context() as patch:
        original=TimestampSigner.get_timestamp;patch.setattr(TimestampSigner,'get_timestamp',lambda self:original(self)-2000)
        preview=upload(client,doc)
    assert advance(client,preview,'review').status_code==409
    preview=upload(client,doc)
    assert advance(client,preview,'confirm',confirm='yes',stage='4').status_code==409
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/energy/import',data={'action':'upload'}).status_code==400
    assert client.post('/energy/review',data={'action':'review','date':str(DAY)}).status_code==400
    assert counts()==[0,0,0,0]


def seed_conflict(owner):
    energy.upsert_document(document(owner,'QA A',total_expenditure_kcal=2400,steps=0),owner)
    energy.upsert_document(document(owner,'QA B',total_expenditure_kcal=2500),owner);db.session.commit()


def final_review(client, **choices):
    response=client.post('/energy/review',data={'date':str(DAY),'action':'review',**choices})
    assert response.status_code==200
    return advance(client,response,'approve',path='/energy/review')


def test_decision_by_source_and_clear_preserve_originals_and_replay(app,client,user):
    seed_conflict(user);login(client);before=energy.state_fingerprint(user,[DAY]);rows=[energy.snapshot(r) for r in db.session.query(DailyEnergy).all()]
    get=client.get('/energy/review?date='+str(DAY));assert get.status_code==200 and b'Pendiente' in get.data
    final=final_review(client,choice_total_calories='source:0',choice_steps='clear')
    assert final.status_code==200 and energy.state_fingerprint(user,[DAY])==before
    response=advance(client,final,'confirm',path='/energy/review',confirm='yes');assert response.status_code==302
    view=energy.view(user,DAY);assert view.total_calories==2400 and view.steps is None
    assert [energy.snapshot(r) for r in db.session.query(DailyEnergy).all()]==rows
    revision=view.revision;events=db.session.query(EnergyEvidenceEvent).count()
    assert advance(client,final,'confirm',path='/energy/review',confirm='yes').status_code==302
    assert energy.view(user,DAY).revision==revision and db.session.query(EnergyEvidenceEvent).count()==events


@pytest.mark.parametrize('value',['-1','NaN','Infinity','10000001','2.5'])
def test_review_invalid_steps_cannot_be_confirmed(app,client,user,value):
    seed_conflict(user);login(client);before=energy.state_fingerprint(user,[DAY])
    response=client.post('/energy/review',data={'date':str(DAY),'action':'review','choice_steps':'manual','value_steps':value})
    assert response.status_code==400 and energy.state_fingerprint(user,[DAY])==before


def test_review_stale_token_modified_ops_and_unknown_source(app,client,user):
    seed_conflict(user);login(client)
    final=final_review(client,choice_total_calories='manual',value_total_calories='2450')
    data=hidden(final);ops=json.loads(data['operations']);ops['total_calories']['value']='9999';data.update(operations=json.dumps(ops),action='confirm',confirm='yes')
    assert client.post('/energy/review',data=data).status_code==409
    energy.edit_day(user,DAY,energy.view(user,DAY).revision,{'total_calories':2420});db.session.commit()
    assert advance(client,final,'confirm',path='/energy/review',confirm='yes').status_code==409
    assert client.post('/energy/review',data={'date':str(DAY),'action':'review','choice_steps':'source:99'}).status_code==400
    assert energy.view(user,DAY).total_calories==2420


def test_two_owners_and_retired_day_cannot_be_reviewed(app,client,user):
    other=User(username='QA C other',role='user');other.set_password('fictional-C');db.session.add(other);db.session.commit();seed_conflict(other.id)
    login(client);before=energy.state_fingerprint(other.id,[DAY])
    assert client.get('/energy/review?date='+str(DAY)+'&user_id='+str(other.id)).status_code==404
    assert energy.state_fingerprint(other.id,[DAY])==before
    seed_conflict(user);current=energy.view(user,DAY);energy.delete_day(user,DAY,current.revision);db.session.commit()
    assert client.get('/energy/review?date='+str(DAY)).status_code==404 and energy.view(user,DAY) is None


def test_previewed_conflict_import_is_not_a_confirmed_resolution(app,client,user):
    seed_conflict(user);login(client);doc=document(user,'QA A',total_expenditure_kcal=2600)
    preview=advance(client,upload(client,doc),'review')
    assert b'Misma fuente antes:' in preview.data and b'2400' in preview.data and b'Conflicto pendiente' in preview.data and b'2600' in preview.data
    final=final_import(client,doc)
    assert 'Conservar propuesta contradictoria' in final.get_data(as_text=True)
    assert advance(client,final,'confirm',confirm='yes').status_code==302
    assert energy.view(user,DAY).total_calories is None
    assert db.session.query(DailyEnergy).filter_by(source='QA A').one().total_calories==2400


def test_declared_empty_metrics_are_not_fabricated(app,client,user):
    login(client);doc=document(user,'QA C',steps=0);doc['data']={'date':str(DAY),'source':'QA C'}
    assert upload(client,doc).status_code==400 and counts()==[0,0,0,0]


def test_json_11_history_identified_without_flattening_or_writes(app,client,user):
    from app.services.exporters.wellness import build_daily_energy_document
    seed_conflict(user);login(client);before=counts()
    bundle=build_daily_energy_document(energy.view(user,DAY),user)
    assert bundle['schema_version']=='1.1'
    response=upload(client,bundle)
    assert response.status_code==400 and b'restore oficial' in response.data and counts()==before
