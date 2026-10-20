"""Fictional B fixtures: owner isolation, bounded audit, retained originals."""
from datetime import date, timedelta
import copy
import io
import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import event
from itsdangerous.timed import TimestampSigner

from app.extensions import db
from app.models import User, DailyEnergy, EnergyDay, EnergyEvidenceEvent, UploadedFile
from app.services import energy_days as energy, energy_provenance as provenance
from app.services.files import store_uploaded_file
from tests.conftest import login
from tests.test_energy_days import document
from werkzeug.datastructures import FileStorage

DAY = date(2040, 2, 3)


def seed(user):
    doc = document(user, 'QA reloj', total_expenditure_kcal=2400, steps=0)
    files = []
    for name, suffix in [('QA-a.json', b'\n'), ('QA-b.json', b'\n\n')]:
        raw = json.dumps(doc).encode() + suffix
        uploaded, _ = store_uploaded_file(FileStorage(stream=io.BytesIO(raw), filename=name), user)
        row = energy.upsert_document(doc, user, source_file=uploaded)
        db.session.commit()
        files.append((uploaded, raw))
    energy.upsert_document(document(user, 'QA archivo', total_expenditure_kcal=2500), user)
    db.session.commit()
    energy.edit_day(user, DAY, energy.view(user,DAY).revision, {'total_calories':2450})
    db.session.commit()
    retired = energy.upsert_document(document(user, 'QA retirada', steps=200), user)
    db.session.commit()
    energy.delete_evidence(user, DAY, retired.public_id, energy.view(user,DAY).revision)
    db.session.commit()
    other = User(username='QA-foreign-'+uuid.uuid4().hex[:8],role='user');other.set_password('fictional-QA-password')
    db.session.add(other);db.session.commit()
    energy.upsert_document(document(other.id, 'QA secret foreign', total_expenditure_kcal=9900),other.id)
    db.session.commit()
    return {'row':row,'files':files,'other':other.id}


@pytest.fixture
def evidence(app, user):
    return seed(user)


def token(user, kind, row):
    files={f.id:f for f in db.session.scalars(db.select(UploadedFile).where(UploadedFile.user_id==user))}
    return provenance.original(user,kind,row,files)['token']


def test_real_history_source_resolution_retirement_and_two_originals(app,client,user,evidence):
    login(client)
    response=client.get('/energy/sources?date=2040-02-03')
    assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
    body=response.get_data(as_text=True)
    assert 'QA retirada' in body and 'Retirada · fuera del canónico' in body
    assert '2450' in body and 'decisión confirmada' in body and '2400' in body and '2500' in body
    assert 'QA secret foreign' not in body
    audit=provenance.audit(user,provenance.filters({}))
    assert len(audit['items'])==audit['total'] and audit['total']>5
    records=db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id==user,
        EnergyEvidenceEvent.source_file_id.is_not(None)).order_by(EnergyEvidenceEvent.id)).all()
    served=[]
    for record in records:
        response=client.post('/energy/original',data={'reference':token(user,'event',record)})
        assert response.status_code==200
        assert response.headers['X-Content-Type-Options']=='nosniff'
        assert response.headers['Cache-Control']=='private, no-store'
        assert response.headers['Content-Disposition'].startswith('attachment;')
        served.append(response.data);response.close()
    assert {raw for _,raw in evidence['files']}==set(served)
    assert energy.view(user,DAY).total_calories==2450


def test_source_and_event_original_survive_retirement_and_day_deletion(app,client,user,evidence):
    login(client)
    original=token(user,'source',evidence['row'])
    energy.delete_day(user,DAY,energy.view(user,DAY).revision);db.session.commit()
    assert energy.view(user,DAY) is None
    response=client.get('/energy/sources?date=2040-02-03')
    assert 'Día retirado' in response.get_data(as_text=True)
    assert 'Decisiones conservadas' in response.get_data(as_text=True)
    assert client.post('/energy/original',data={'reference':original}).data==evidence['files'][0][1]
    response=client.get('/energy/history?from=2040-02-03&to=2040-02-03&operation=delete_day')
    assert response.status_code==200 and 'Retirada del día' in response.get_data(as_text=True)
    assert energy.view(user,DAY) is None


def test_legacy_original_without_evidence_hash_uses_file_hash_without_backfill(app,client,user,evidence):
    login(client);row=evidence['row'];row.source_file_sha256=None;db.session.commit()
    body=client.get('/energy/sources?date=2040-02-03').get_data(as_text=True)
    assert 'La evidencia antigua no registró su propio hash' in body
    response=client.post('/energy/original',data={'reference':token(user,'source',row)})
    assert response.status_code==200 and response.data==evidence['files'][0][1]
    response.close();assert row.source_file_sha256 is None


def test_pagination_beyond_100_and_combined_filters(app,client,user,evidence):
    for offset in range(110):
        energy.upsert_document(document(user,'QA largo',day=DAY-timedelta(days=offset+1),steps=offset),user)
    db.session.commit();login(client)
    collected=[]
    first=provenance.audit(user,provenance.filters({}))
    assert first['total']>100 and first['pages']>=5
    for page in range(1,first['pages']+1):
        part=provenance.audit(user,provenance.filters({'page':str(page)}))
        assert len(part['items'])<=25
        collected += [(item['date'],item['source'],item['operation'],item['created_at'],
                       item['original']['name'] if item['original'] else None) for item in part['items']]
    assert len(collected)==len(set(collected))==first['total']
    assert provenance.audit(user,provenance.filters({'page':'999999999'}))['page']==first['pages']
    selected={'from':'2040-02-01','to':'2040-02-02','source':'QA largo','operation':'import'}
    filtered=provenance.audit(user,provenance.filters(selected))
    assert filtered['total']==2 and all(row['source']=='QA largo' for row in filtered['items'])
    response=client.get('/energy/history?source=QA+largo&operation=import')
    body=response.get_data(as_text=True)
    assert 'rel="next"' in body and 'source=QA+largo' in body and 'operation=import' in body
    assert 'QA secret foreign' not in body
    assert client.get('/energy/history?source=QA+largo&page=5').status_code==200


def test_no_raw_payload_ids_paths_or_hashes_in_page(app,client,user,evidence):
    row=db.session.scalar(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id==user).order_by(EnergyEvidenceEvent.id))
    payload=copy.deepcopy(row.payload_json);payload['incoming']['PRIVATE_MARKER']='QA-raw-should-not-render'
    payload['record']['values']['notes']='QA-private-note-not-rendered';row.payload_json=payload;db.session.commit()
    login(client)
    body=client.get('/energy/history').get_data(as_text=True)
    for forbidden in [row.event_key,evidence['files'][0][0].sha256,evidence['files'][0][0].storage_path,
                      'QA-raw-should-not-render','QA-private-note-not-rendered','payload_json','evidence_public_id']:
        assert forbidden not in body
    assert 'Valores conservados' in body and 'QA reloj' in body


def test_historical_source_is_not_relabelled_and_missing_origin_not_invented(app,user,evidence):
    evidence['row'].source='QA renamed later'
    db.session.commit()
    result=provenance.audit(user,provenance.filters({'source':'QA reloj'}))
    assert result['total']>0 and all(item['source']=='QA reloj' for item in result['items'])
    row=db.session.scalar(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id==user).order_by(EnergyEvidenceEvent.id))
    payload=copy.deepcopy(row.payload_json);payload['record'].pop('source');row.payload_json=payload;db.session.commit()
    result=provenance.audit(user,provenance.filters({}))
    assert any(item['source']=='Origen no disponible' for item in result['items'])
    assert 'QA renamed later' not in result['source_choices']


def test_moved_day_keeps_previous_date_visible_and_identity(app,client,user,evidence):
    original_id=evidence['row'].public_id
    destination=DAY+timedelta(days=2)
    energy.edit_day(user,DAY,energy.view(user,DAY).revision,{},new_date=destination);db.session.commit()
    result=provenance.audit(user,provenance.filters({'operation':'edit_day'}))
    assert any(item['date']==destination and item['previous_date']==DAY for item in result['items'])
    login(client);body=client.get('/energy/history?operation=edit_day').get_data(as_text=True)
    assert 'Fecha anterior del registro' in body and 'date=2040-02-03' in body
    assert evidence['row'].public_id==original_id and energy.view(user,DAY) is None


def test_conflicting_proposal_visible_without_changing_original(app,client,user,evidence):
    energy.upsert_document(document(user,'QA reloj',total_expenditure_kcal=2600),user);db.session.commit()
    result=provenance.audit(user,provenance.filters({'operation':'conflict'}))
    assert result['total']==1 and result['items'][0]['proposals'][0]['value']==2600
    assert result['items'][0]['metrics'][0]['value']==2400 and energy.view(user,DAY).total_calories is None
    login(client);body=client.get('/energy/history?operation=conflict').get_data(as_text=True)
    assert 'Propuesta conservada · no aplicada' in body and '2600' in body
    body=client.get('/energy/sources?date=2040-02-03').get_data(as_text=True)
    assert 'campos pendientes' in body and '2600' in body


def test_owner_bound_tokens_and_forged_client_owner(app,client,user,evidence):
    original=token(user,'source',evidence['row'])
    with client.session_transaction() as session:session['_user_id']=str(evidence['other']);session['_fresh']=True
    assert client.post('/energy/original',data={'reference':original}).status_code==404
    body=client.get(f'/energy/history?user_id={user}').get_data(as_text=True)
    assert 'QA secret foreign' in body and 'QA reloj' not in body
    body=client.get(f'/energy/sources?date=2040-02-03&user_id={user}').get_data(as_text=True)
    assert 'QA reloj' not in body
    assert provenance.sources(evidence['other'],DAY)['canonical'].total_calories==9900


@pytest.mark.parametrize('query',['from=bad','to=0001-01-01','from=2040-03-01&to=2040-01-01','page=0',
                                  'page=oops','operation=../private','source='+'x'*33])
def test_bad_filters(app,client,user,query):
    login(client)
    assert client.get('/energy/history?'+query).status_code==400


def test_expired_tampered_missing_and_unbound_tokens(app,client,user,evidence,monkeypatch):
    login(client);original=token(user,'source',evidence['row'])
    assert client.post('/energy/original',data={'reference':original+'x'}).status_code==404
    assert client.post('/energy/original',data={'reference':'not-a-token'}).status_code==404
    assert client.post('/energy/original',data={'reference':provenance._signer().dumps([user,'source',999999,1,'bad'])}).status_code==404
    now=TimestampSigner.get_timestamp(TimestampSigner('QA'))
    monkeypatch.setattr(TimestampSigner,'get_timestamp',lambda self:now+901)
    assert client.post('/energy/original',data={'reference':original}).status_code==404


@pytest.mark.parametrize('change',['bytes','size','metadata_hash','reference_hash','both_hashes'])
def test_changed_original_never_served(app,client,user,evidence,change):
    login(client);row=evidence['row'];original=token(user,'source',row);file=evidence['files'][0][0]
    path=Path(app.config['DATA_ROOT'])/file.storage_path
    if change=='bytes':path.write_bytes(b'X'*file.size_bytes)
    if change=='size':file.size_bytes+=1
    if change=='metadata_hash':file.sha256='0'*64
    if change=='reference_hash':row.source_file_sha256='0'*64
    if change=='both_hashes':file.sha256=row.source_file_sha256='0'*64
    db.session.commit()
    assert client.post('/energy/original',data={'reference':original}).status_code==404


@pytest.mark.parametrize('location',['outside','other_owner','symlink'])
def test_original_storage_boundaries(app,client,user,evidence,location,tmp_path):
    login(client);row=evidence['row'];original=token(user,'source',row);file,raw=evidence['files'][0]
    if location=='outside':
        p=tmp_path/'QA-outside.json';p.write_bytes(raw);file.storage_path=str(p)
    elif location=='other_owner':
        p=Path(app.config['UPLOAD_ROOT'])/f'user_{evidence["other"]}'/'QA-other.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        file.storage_path=p.relative_to(app.config['DATA_ROOT']).as_posix()
    else:
        source=Path(app.config['DATA_ROOT'])/file.storage_path;link=source.with_name('QA-link')
        try:os.symlink(source,link)
        except OSError:pytest.skip('Platform does not allow synthetic symlink creation')
        file.storage_path=link.relative_to(app.config['DATA_ROOT']).as_posix()
    db.session.commit()
    assert client.post('/energy/original',data={'reference':original}).status_code==404


def test_file_swap_after_resolver_cannot_send_changed_bytes(app,client,user,evidence,monkeypatch):
    login(client);original=token(user,'source',evidence['row'])
    real=provenance.resolve_uploaded_download
    def swap(file,**kwargs):
        path=real(file,**kwargs);path.write_bytes(b'Z'*file.size_bytes);return path
    monkeypatch.setattr(provenance,'resolve_uploaded_download',swap)
    assert client.post('/energy/original',data={'reference':original}).status_code==404


def test_gets_and_downloads_never_write_or_change_history(app,client,user,evidence):
    login(client)
    models=[DailyEnergy,EnergyDay,EnergyEvidenceEvent,UploadedFile]
    def snapshot():
        return [[{c.name:copy.deepcopy(getattr(row,c.name)) for c in model.__table__.columns}
                 for row in db.session.scalars(db.select(model).order_by(model.id))] for model in models]
    before=snapshot();writes=[]
    def capture(conn,cursor,statement,params,context,executemany):
        if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):writes.append(statement)
    event.listen(db.engine,'before_cursor_execute',capture)
    try:
        assert client.get('/energy/sources?date=2040-02-03').status_code==200
        assert client.get('/energy/sources?date=2041-01-01').status_code==200
        assert client.get('/energy/history').status_code==200
        assert client.post('/energy/original',data={'reference':token(user,'source',evidence['row'])}).status_code==200
        assert client.get('/energy?date=2040-02-03&period=7').status_code==200
    finally:event.remove(db.engine,'before_cursor_execute',capture)
    assert writes==[] and snapshot()==before


def test_login_required(client):
    for path in ['/energy/sources','/energy/history']:
        assert client.get(path).status_code==302


def test_original_download_requires_csrf_when_enabled(app,client,user,evidence):
    import re,html
    login(client);app.config['WTF_CSRF_ENABLED']=True
    body=client.get('/energy/sources?date=2040-02-03').get_data(as_text=True)
    csrf=html.unescape(re.search(r'name="csrf_token"[^>]*value="([^"]*)"',body)[1])
    ref=token(user,'source',evidence['row'])
    assert client.post('/energy/original',data={'reference':ref}).status_code==400
    response=client.post('/energy/original',data={'reference':ref,'csrf_token':csrf})
    assert response.status_code==200
    response.close()
