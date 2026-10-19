"""Delivery A: synthetic fixtures; canonical parity and read-only consultation."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import copy

import pytest
from sqlalchemy import event
from flask import url_for

from app.extensions import db
from app.models import User, DailyNutrition, DailyEnergy, EnergyDay, EnergyEvidenceEvent
from app.services import energy_days as energy
from app.services.energy_history import consultation, local_today
from app.services.nutrition_history import history
from app.services.daily_balance import daily_balance
from tests.conftest import login
from tests.test_energy_days import document

DAY = date(2040, 2, 3)


def seed(owner):
    """Shared by real-Flask QA and isolated-engine tests; no real data."""
    for offset in range(125):
        target = DAY - timedelta(days=offset)
        energy.upsert_document(document(owner, 'QA gasto', day=target,
            total_expenditure_kcal=2400 + offset, active_expenditure_kcal=600,
            resting_expenditure_kcal=1800), owner)
        db.session.add(DailyNutrition(user_id=owner, date=target, source='QA Nutrition', calories=2200))
    energy.upsert_document(document(owner, 'QA pasos', steps=8200, distance_meters=6400), owner)
    # Both balance signs, zero, partial, contradiction, resolution, retirement.
    for ago, value in [(1, 2000), (3, 0)]:
        day = DAY - timedelta(days=ago)
        energy.edit_day(owner, day, energy.view(owner, day).revision, {'total_calories': value})
    partial = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id==owner, DailyNutrition.date==DAY-timedelta(days=2)))
    partial.nutrition_summary_json = {'energy': {'value':'2200', 'state':'partial'}}
    for ago in [2, 4]:
        day = DAY - timedelta(days=ago)
        energy.upsert_document(document(owner, 'QA contradicción', day=day, total_expenditure_kcal=3000), owner)
    day = DAY - timedelta(days=4)
    energy.edit_day(owner, day, energy.view(owner,day).revision, {'total_calories': 2600})
    retired = energy.upsert_document(document(owner, 'QA retirada', total_expenditure_kcal=4000), owner)
    energy.delete_evidence(owner, DAY, retired.public_id, energy.view(owner,DAY).revision)
    deleted = DAY - timedelta(days=5)
    energy.delete_day(owner, deleted, energy.view(owner,deleted).revision)
    # Partial energy day outside the continuous fixture range.
    energy.upsert_document(document(owner, 'QA sólo pasos', day=DAY+timedelta(days=1), steps=0), owner)
    db.session.commit()


@pytest.fixture
def seeded(app, user):
    seed(user)
    return user


@pytest.mark.parametrize('period',[7,30,90])
def test_exact_nutrition_daily_balance_and_warmup(app,seeded,period):
    result=consultation(seeded,DAY,period)
    nutrition=history(seeded,DAY,period)
    assert len(result['charts'][0]['samples'])==period
    for index,p in enumerate(nutrition['points']):
        expenditure,intake,balance=[c['samples'][index] for c in result['charts']]
        assert expenditure['value']==p['expended']
        assert intake['value']==p['values']['calories']
        assert balance['value']==p['balance']==daily_balance(seeded,p['date'])['balance']
        for key,sample in [('expended',expenditure),('intake',intake),('balance',balance)]:
            assert sample['rolling']==p['rolling_energy'][key]
            assert sample['rolling_days']==p['rolling_energy_days'][key]
    # First visible window includes preceding six days, not just the plot.
    expected=history(seeded,DAY-timedelta(days=period-1),7)['points'][-1]
    assert result['charts'][0]['samples'][0]['rolling']==expected['rolling_energy']['expended']
    assert result['fields'][0]['value']==2400  # No evidence sum / retired source.
    assert next(f for f in result['fields'] if f['key']=='steps')['value']==8200


def test_states_deleted_partial_zero_resolved_and_old_history(app,seeded):
    partial=consultation(seeded,DAY+timedelta(days=1),7)
    assert partial['day_state']=='partial'
    assert partial['fields'][0]['value'] is None and partial['fields'][3]['state']=='zero'
    conflict=consultation(seeded,DAY-timedelta(days=2),7)
    assert conflict['day_state']=='conflict'
    assert conflict['charts'][0]['samples'][-1]['state']=='conflict'
    assert conflict['charts'][1]['samples'][-1]['state']=='partial'
    assert conflict['charts'][2]['samples'][-1]['value'] is None
    resolved=consultation(seeded,DAY-timedelta(days=4),7)
    assert resolved['fields'][0]['value']==2600 and resolved['fields'][0]['source']=='Resolución confirmada'
    deleted=consultation(seeded,DAY-timedelta(days=5),7)
    assert deleted['selected'] is None and deleted['day_state']=='unknown'
    zero=consultation(seeded,DAY-timedelta(days=3),7)
    assert zero['fields'][0]['state']=='zero' and zero['charts'][0]['samples'][-1]['bar_height']==2
    old=consultation(seeded,DAY+timedelta(days=365),7)
    assert old['selected'] is None and old['latest'].date==DAY+timedelta(days=1)
    assert old['trends']==[]
    assert consultation(seeded,DAY-timedelta(days=124),7)['selected'] is not None


@pytest.mark.parametrize('target',[date(2040,1,1),date(2040,2,29),date(2040,12,31),date(2041,1,1)])
def test_dynamic_calendar_month_year(app,user,target):
    result=consultation(user,target,7)
    cells=[c for week in result['calendar_weeks'] for c in week if c]
    assert cells[0]['date']==target.replace(day=1)
    assert cells[-1]['date']==result['month_end']
    assert result['previous_month'].month!=target.month and result['next_month'].month!=target.month


def test_timezone_changes_only_today(app,user):
    owner=db.session.get(User,user)
    now=datetime(2040,1,1,1,tzinfo=timezone.utc)
    owner.timezone='America/Mexico_City'
    assert local_today(owner,now=now)[0]==date(2039,12,31)
    owner.timezone='Asia/Tokyo'
    assert local_today(owner,now=now)[0]==date(2040,1,1)
    owner.timezone='invalid/QA'
    assert local_today(owner,now=now)==(date(2040,1,1),'UTC')


def test_owner_isolation_and_all_gets_are_read_only(app,client,seeded):
    other=User(username='QA-other',role='user');other.set_password('QA-fictional-password')
    db.session.add(other);db.session.commit()
    assert consultation(other.id,DAY,7)['selected'] is None
    assert consultation(other.id,DAY,7)['latest'] is None
    assert consultation(other.id,DAY,7)['trends']==[]
    before={model.__tablename__:[{column.name:copy.deepcopy(getattr(row,column.name)) for column in model.__table__.columns}
            for row in db.session.scalars(db.select(model).order_by(model.id))]
            for model in (DailyEnergy,DailyNutrition,EnergyDay,EnergyEvidenceEvent)}
    login(client)
    writes=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):
            writes.append(statement.split()[0])
    event.listen(db.engine,'before_cursor_execute',capture)
    try:
        for target in [DAY, DAY+timedelta(days=500), date(2040,1,1)]:
            response=client.get(f'/energy?date={target}&period=7&user_id={other.id}')
            assert response.status_code==200
            html=response.get_data(as_text=True)
            assert 'Tabla equivalente' in html and 'Volver a interfaz actual' in html
            assert 'QA retirada' not in html and 'raw_payload' not in html
        with app.test_request_context():
            anchor=energy.view(seeded,DAY).id
            routes=[url_for(endpoint, **({'record_id':anchor} if endpoint in (
                'wellness.energy_detail','wellness.energy_edit','wellness.energy_delete') else {}))
                for endpoint in ('wellness.energy_list','wellness.energy_import','wellness.manual_energy',
                                 'wellness.energy_detail','wellness.energy_edit','wellness.energy_delete')]
        for route in routes:
            assert client.get(route).status_code==200
    finally:
        event.remove(db.engine,'before_cursor_execute',capture)
    assert writes==[]
    after={model.__tablename__:[{column.name:copy.deepcopy(getattr(row,column.name)) for column in model.__table__.columns}
           for row in db.session.scalars(db.select(model).order_by(model.id))]
           for model in (DailyEnergy,DailyNutrition,EnergyDay,EnergyEvidenceEvent)}
    assert before==after


@pytest.mark.parametrize('query',['date=bad','date=0001-01-01','date=9999-12-31','period=all','period=1000000'])
def test_invalid_parameters(app,client,user,query):
    login(client)
    assert client.get('/energy?'+query).status_code==400


def test_login_required(client):
    assert client.get('/energy').status_code==302
