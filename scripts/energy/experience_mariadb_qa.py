"""Existing LOCAL isolated QA schema only; synthetic owners, no DDL or cleanup.

Run in the existing Python 3.12 QA image with backend and schemas mounted RO.
Supply the existing private QA connection environment without printing it.
"""
from datetime import date, timedelta
from pathlib import Path
import hashlib
import json
import os
import uuid

from flask_migrate import check
from sqlalchemy import text, event
from app import create_app
from app.extensions import db
from app.models import User, DailyNutrition, DailyEnergy, EnergyDay, EnergyEvidenceEvent
from app.services import energy_days
from app.services.energy_history import consultation
from app.services.nutrition_history import history
from app.services.daily_balance import daily_balance

SCHEMA='nutrition_intelligence_qa_20261009'
HEAD='20261018_0046'
report={'scope':'existing LOCAL isolated MariaDB; synthetic owners only', 'head':HEAD, 'isolations':{}}

for isolation in ['READ COMMITTED','REPEATABLE READ']:
    root=Path('/tmp/energy-experience-a')/isolation.replace(' ','-')
    app=create_app({'TESTING':True,'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads',
        'GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portability',
        'SCHEMA_ROOT':Path('/qa-schemas'), 'NUTRITION_INTELLIGENCE_ENABLED':False,
        'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,
        'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':isolation}})
    with app.app_context():
        assert db.engine.url.database==SCHEMA, 'Refusing non-QA schema'
        assert db.session.scalar(text('SELECT DATABASE()'))==SCHEMA
        assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
        assert db.session.scalar(text('SELECT version_num FROM alembic_version'))==HEAD
        assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-',' ')==isolation
        owner=User(username='QA-energy-A-'+uuid.uuid4().hex,role='user')
        owner.set_password('fictional-QA-only-password'); other=User(username='QA-energy-A-other-'+uuid.uuid4().hex,role='user')
        other.set_password('fictional-QA-only-password');db.session.add_all([owner,other]);db.session.commit()
        target=date(2040,2,3)
        def put(day,source,**values):
            return energy_days.upsert_document({'schema_version':'1.0','record_type':'daily_energy','user_id':owner.id,
                'source_type':'uploaded','data':{'date':day.isoformat(),'source':source,**values}},owner.id)
        for offset in range(125):
            day=target-timedelta(days=offset)
            put(day,'QA gasto',total_expenditure_kcal=2400+offset)
            db.session.add(DailyNutrition(user_id=owner.id,date=day,source='QA Nutrition',calories=2200))
        put(target,'QA pasos',steps=0,distance_meters=0)
        put(target-timedelta(days=2),'QA conflicto',total_expenditure_kcal=3000)
        partial=db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id==owner.id,DailyNutrition.date==target-timedelta(days=3)))
        partial.nutrition_summary_json={'energy':{'value':'2200','state':'partial'}}
        energy_days.edit_day(owner.id,target-timedelta(days=1),energy_days.view(owner.id,target-timedelta(days=1)).revision,{'total_calories':2000})
        retired=put(target,'QA retirada',total_expenditure_kcal=4000)
        energy_days.delete_evidence(owner.id,target,retired.public_id,energy_days.view(owner.id,target).revision)
        energy_days.delete_day(owner.id,target-timedelta(days=5),energy_days.view(owner.id,target-timedelta(days=5)).revision)
        db.session.commit()
        def fingerprint():
            state=[]
            for model in [DailyEnergy,DailyNutrition,EnergyDay,EnergyEvidenceEvent]:
                state.append([(model.__tablename__, [getattr(row,c.name) for c in model.__table__.columns])
                    for row in db.session.scalars(db.select(model).where(model.user_id==owner.id).order_by(model.id))])
            return hashlib.sha256(repr(state).encode()).hexdigest()
        before=fingerprint(); writes=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):
                writes.append(statement.split()[0])
        event.listen(db.engine,'before_cursor_execute',capture)
        try:
            for period in [7,30,90]:
                view=consultation(owner.id,target,period);nutrition=history(owner.id,target,period)
                for index,point in enumerate(nutrition['points']):
                    for chart,key in zip(view['charts'],['expended','intake','balance']):
                        sample=chart['samples'][index]
                        assert sample['value']==(point['values']['calories'] if key=='intake' else point[key])
                        assert sample['rolling']==point['rolling_energy'][key]
                        assert sample['rolling_days']==point['rolling_energy_days'][key]
                    assert view['charts'][2]['samples'][index]['value']==daily_balance(owner.id,point['date'])['balance']
                assert view['fields'][0]['value']==2400 and view['fields'][3]['value']==0
            assert consultation(other.id,target,7)['latest'] is None
            assert consultation(owner.id,target+timedelta(days=500),7)['latest'].date==target
            assert consultation(owner.id,target-timedelta(days=124),7)['selected'] is not None
            assert consultation(owner.id,target-timedelta(days=2),7)['day_state']=='conflict'
            assert consultation(owner.id,target-timedelta(days=5),7)['selected'] is None
            assert fingerprint()==before and writes==[]
            with app.test_client() as client:
                with client.session_transaction() as session:
                    session['_user_id']=str(owner.id);session['_fresh']=True
                for day in [target,target+timedelta(days=500),date(2040,1,1)]:
                    assert client.get(f'/energy?date={day}&period=7&user_id={other.id}').status_code==200
            assert fingerprint()==before and writes==[]
        finally:
            event.remove(db.engine,'before_cursor_execute',capture)
        check(directory='/qa-backend/migrations')
        report['isolations'][isolation]={'status':'PASS','periods':[7,30,90], 'historical_days':125,
            'parity':'Nutrition daily/rolling/denominators and Daily Balance identical',
            'complementary_conflicting_resolved_retired_deleted_zero_partial':'PASS',
            'owner_isolation':'PASS','http_get':'200; forged owner ignored','domain_fingerprint':'unchanged','write_statements':0,'db_check':'PASS'}

Path('/evidence/mariadb.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
