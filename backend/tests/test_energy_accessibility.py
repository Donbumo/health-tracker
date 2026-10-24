"""D: fictional date boundaries, accessible recovery and owner-only read facade."""
from datetime import date
import re
from itsdangerous.timed import TimestampSigner

import pytest
from flask import g
from sqlalchemy import event

from app.extensions import db
from app.models import DailyEnergy, EnergyEvidenceEvent, User
from app.services import energy_days as energy
from app.services.energy_history import consultation, MIN_DAY, MAX_DAY
from tests.conftest import login
from tests.test_energy_days import document, DAY
from tests.test_energy_guided import seed_conflict, counts, advance, final_review, hidden


@pytest.mark.parametrize('target', [MIN_DAY, date(1900,1,2), date(1900,2,1), date(9998,11,30), date(9998,12,30), MAX_DAY])
@pytest.mark.parametrize('period', [7,30,90])
def test_supported_boundary_navigation_without_writes(app, client, user, target, period):
    login(client)
    writes=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):
            writes.append(statement.split()[0])
    event.listen(db.engine,'before_cursor_execute',capture)
    try:
        result=consultation(user,target,period)
        for key in ('previous','next','previous_month','next_month'):
            assert result[key] is None or MIN_DAY <= result[key] <= MAX_DAY
        response=client.get(f'/energy?date={target}&period={period}')
        assert response.status_code==200
        html=response.get_data(as_text=True)
        links=re.findall(r'href="([^"]+)"',html)
        assert not any('date=1899' in link or 'date=9999' in link for link in links)
        if target in (MIN_DAY,MAX_DAY):
            assert html.count('role="link" aria-disabled="true"')==2
        assert '<dd>' in html and 'aria-atomic="true"' in html
    finally:
        event.remove(db.engine,'before_cursor_execute',capture)
    assert writes==[]


def test_outside_range_history_preserved_latest_link_safe_and_owner_only(app,client,user):
    other=User(username='QA-D-other',role='user');other.set_password('fictional-D-password')
    db.session.add(other);db.session.commit()
    for owner,target,source in ((user,MAX_DAY,'QA D last valid'),(user,date(9999,1,1),'QA D outside retained'),(other.id,MAX_DAY,'QA D foreign')):
        energy.upsert_document(document(owner,source,day=target,steps=12),owner)
    db.session.commit();before=counts();login(client)
    assert consultation(user,MIN_DAY,7)['latest'].date==MAX_DAY
    response=client.get('/energy/history')
    assert response.status_code==200
    html=response.get_data(as_text=True)
    assert 'QA D outside retained' in html and 'fuera del intervalo' in html
    assert 'date=9999' not in html and 'QA D foreign' not in html
    assert counts()==before and db.session.query(DailyEnergy).count()==3


@pytest.mark.parametrize('query,invalid', [('date=bad&period=7','date'),('date=1900-01-01&period=all','period'),('date=9999-01-01&period=all','both')])
def test_recoverable_query_errors_preserve_valid_field(app,client,user,query,invalid):
    login(client);response=client.get('/energy?'+query)
    assert response.status_code==400
    html=response.get_data(as_text=True)
    assert 'role="alert" tabindex="-1" autofocus' in html
    assert html.count('aria-invalid="true"')==(2 if invalid=='both' else 1)
    if invalid=='date': assert '<option value="7" selected>' in html
    if invalid=='period': assert 'value="1900-01-01"' in html
    assert client.get('/energy?date=1900-01-01&period=7').status_code==200


def test_invalid_manual_preserves_draft_errors_and_requires_fresh_review(app,client,user):
    seed_conflict(user);login(client);before=counts();state=energy.state_fingerprint(user,[DAY])
    data={'date':str(DAY),'action':'review','choice_steps':'manual','value_steps':'2.5',
          'choice_total_calories':'manual','value_total_calories':'2450','choice_notes':'manual','value_notes':'<QA draft>'}
    response=client.post('/energy/review',data=data)
    assert response.status_code==400
    html=response.get_data(as_text=True)
    assert 'aria-describedby="eg-help-steps eg-error-steps" aria-invalid="true"' in html
    assert 'href="#eg-value-steps"' in html and 'value="2450"' in html and '&lt;QA draft&gt;' in html
    assert 'name="review_token"' not in html
    assert counts()==before and energy.state_fingerprint(user,[DAY])==state
    corrected=client.post('/energy/review',data={**data,'value_steps':'0'})
    assert corrected.status_code==200
    final=advance(client,corrected,'approve',path='/energy/review')
    assert final.status_code==200 and counts()==before
    assert advance(client,final,'confirm',path='/energy/review',confirm='yes').status_code==302
    assert energy.view(user,DAY).steps==0 and energy.view(user,DAY).total_calories==2450
    confirmed=counts()
    assert confirmed[2]>before[2]
    assert advance(client,final,'confirm',path='/energy/review',confirm='yes').status_code==302
    assert counts()==confirmed


@pytest.mark.parametrize('route,status', [('/energy',200),('/energy?date=bad',400),('/energy/import',200),('/energy/review?date=2040-02-03',404),('/energy/history',200),('/daily-energy',200)])
def test_private_headers_cover_success_error_and_redirect(app,client,user,route,status):
    unauth=client.get(route)
    assert unauth.status_code==302 and unauth.headers['Cache-Control']=='private, no-store'
    login(client);response=client.get(route)
    assert response.status_code==status
    assert response.headers['Cache-Control']=='private, no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert 'no-store' not in client.get('/healthz').headers.get('Cache-Control','')


def test_csrf_error_not_cached(app,client,user):
    login(client);app.config['WTF_CSRF_ENABLED']=True
    response=client.post('/energy/review',data={'date':str(DAY)})
    assert response.status_code==400 and response.headers['Cache-Control']=='private, no-store'


@pytest.mark.parametrize('path',['/energy/sources?date=bad','/energy/history?from=2040-02-03&to=2040-01-01'])
def test_provenance_errors_have_accessible_recovery(app,client,user,path):
    login(client);before=counts();response=client.get(path)
    assert response.status_code==400 and b'role="alert" tabindex="-1" autofocus' in response.data
    assert b'/energy/history?filters=1#ep-filters' in response.data
    recovery=client.get('/energy/history?filters=1')
    assert b'id="ep-filters" class="ee-card ep-filter-panel" open' in recovery.data
    assert counts()==before


@pytest.mark.parametrize('failure',['expired','stale','tampered'])
def test_unusable_review_keeps_manual_draft_without_renewing_or_writing(app,client,user,monkeypatch,failure):
    seed_conflict(user);login(client)
    choices={'choice_total_calories':'manual','value_total_calories':'2460',
             'choice_steps':'clear','choice_notes':'manual','value_notes':'<QA preserved draft>'}
    if failure=='expired':
        original=TimestampSigner.get_timestamp
        with monkeypatch.context() as patch:
            patch.setattr(TimestampSigner,'get_timestamp',lambda self:original(self)-903)
            final=final_review(client,**choices)
    else:
        final=final_review(client,**choices)
    data={**hidden(final),'action':'confirm','confirm':'yes'}
    if failure=='tampered':data['review_token']='QA-invalid-signature'
    if failure=='stale':
        energy.edit_day(user,DAY,energy.view(user,DAY).revision,{'total_calories':2470});db.session.commit()
    before=counts();state=energy.state_fingerprint(user,[DAY])
    response=client.post('/energy/review',data=data)
    assert response.status_code==409
    body=response.get_data(as_text=True)
    assert 'value="2460"' in body and '&lt;QA preserved draft&gt;' in body
    assert 'name="review_token"' not in body and 'No se renovó la firma anterior.' in body
    assert counts()==before and energy.state_fingerprint(user,[DAY])==state
    # The unusable confirmation stays unusable; only an explicit new review
    # through the existing flow can create a fresh signed confirmation.
    assert client.post('/energy/review',data=data).status_code==409
    fresh=client.post('/energy/review',data={**hidden(response),'action':'review',**choices})
    assert fresh.status_code==200 and counts()==before
    final=advance(client,fresh,'approve',path='/energy/review')
    assert final.status_code==200 and energy.state_fingerprint(user,[DAY])==state
    assert advance(client,final,'confirm',path='/energy/review',confirm='yes').status_code==302
    assert energy.view(user,DAY).total_calories==2460 and energy.view(user,DAY).steps is None


def test_stale_review_drops_source_indexes_before_fresh_choice(app,client,user):
    seed_conflict(user);login(client)
    final=final_review(client,choice_total_calories='source:0')
    energy.upsert_document(document(user,'QA third source',steps=3),user);db.session.commit()
    before=counts();response=advance(client,final,'confirm',path='/energy/review',confirm='yes')
    assert response.status_code==409 and counts()==before
    select=response.get_data(as_text=True).split('id="eg-choice-total_calories"',1)[1].split('</select>',1)[0]
    assert 'value="keep" selected' in select and 'value="source:0" selected' not in select


def test_rejected_foreign_token_rebuilds_only_effective_owners_day(app,client,user):
    seed_conflict(user);login(client)
    other=User(username='QA second recovery owner',role='user');other.set_password('fictional-D-password')
    db.session.add(other);db.session.commit()
    energy.upsert_document(document(other.id,'QA second owner source',total_expenditure_kcal=1300),other.id);db.session.commit()
    final=final_review(client,choice_total_calories='manual',value_total_calories='2460')
    before=counts();states=[energy.state_fingerprint(owner,[DAY]) for owner in (user,other.id)]
    with client.session_transaction() as session:session['_user_id']=str(other.id);session['_fresh']=True
    g.pop('_login_user',None)
    response=advance(client,final,'confirm',path='/energy/review',confirm='yes',user_id=str(user))
    assert response.status_code==409 and counts()==before
    body=response.get_data(as_text=True)
    assert 'QA second owner source' in body and 'QA A' not in body and 'QA B' not in body
    assert 'name="review_token"' not in body
    assert [energy.state_fingerprint(owner,[DAY]) for owner in (user,other.id)]==states
