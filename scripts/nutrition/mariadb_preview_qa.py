"""Issue #32 on a disposable LOCAL MariaDB, real 0046, RC/RR.

Only nutrition_preview_qa on loopback:33432 is accepted. Start a new MariaDB
container with tmpfs, never a personal DB or persistent volume. No .env reads.
"""
import copy
import io
import json
import os
import re
import sys
import subprocess
import tempfile
import threading
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import timedelta
from html import unescape
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from flask import g
from flask_migrate import upgrade,check
from sqlalchemy import event,text
from app import create_app
from app.extensions import db
from app.models import User,MealLog,FoodProduct,NutritionImportDraft,NutritionImportReceipt
from app.services import nutrition_import as imports,nutrition_import_review as review
from app.services.exporters.user_data import build_user_data_document
from app.services.account_restore import AccountRestoreService
from app.services.nutrition_portability import export_bundle,semantic_snapshot
from qa_preview_fixtures import source,table

isolation=os.environ.get('QA_ISOLATION','READ COMMITTED')
assert isolation in {'READ COMMITTED','REPEATABLE READ'}
root=Path(tempfile.mkdtemp(prefix='issue32-mariadb-qa-'))
app=create_app(dict(SECRET_KEY='fictional-issue32-maria-signing-key-over-32-characters',
    API_TOKEN_SIGNING_KEY='fictional-issue32-maria-api-key-over-32-characters',
    SQLALCHEMY_DATABASE_URI='mysql+pymysql://root:fictional-issue32-db-password@127.0.0.1:33432/nutrition_preview_qa?charset=utf8mb4',
    SQLALCHEMY_ENGINE_OPTIONS={'isolation_level':isolation,'pool_pre_ping':True},
    DATA_ROOT=root,UPLOAD_ROOT=root/'uploads/raw',GENERATED_UPLOAD_ROOT=root/'generated',PORTABILITY_ROOT=root/'portable',
    SCHEMA_ROOT=ROOT/'schemas',NUTRITION_INTELLIGENCE_ENABLED=True,APP_TIMEZONE='UTC',
    AI_ENABLED=False,NUTRITION_EXTERNAL_LOOKUP_ENABLED=False))
report={'status':'PASS','data':'fictional only, disposable MariaDB tmpfs','isolation':isolation,'cases':[]}


class Client:
    def __init__(self):self.client=app.test_client()
    def get(self,*args,**kwargs):
        with app.app_context():return self.client.get(*args,**kwargs)
    def post(self,*args,**kwargs):
        with app.app_context():return self.client.post(*args,**kwargs)


def login(name):
    client=Client();page=client.get('/login')
    csrf=unescape(re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page.text)[1])
    assert client.post('/login',data=dict(username=name,password='fictional-maria-preview-password',csrf_token=csrf)).status_code==302
    return client,csrf


def signed(client,key):
    page=client.get('/nutrition/import/'+key)
    assert page.status_code==200
    match=re.search(r'name="token" value="([^"]+)"',page.text)
    assert match,'Blocked preview has no signature'
    return unescape(match[1])


def owner():
    with app.app_context():
        user=User(username='QA Issue32 '+uuid.uuid4().hex[:12],role='user')
        user.set_password('fictional-maria-preview-password');db.session.add(user);db.session.commit()
        return user.id,user.username


def counts(uid):
    return {model.__tablename__:db.session.scalar(db.select(db.func.count(model.id)).where(model.user_id==uid))
        for model in [MealLog,FoodProduct,NutritionImportReceipt]}


with app.app_context():
    assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_preview_qa'
    db.session.rollback()
    upgrade(directory=str(ROOT/'backend/migrations'))
    assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
    check(directory=str(ROOT/'backend/migrations'))
    report['head']='20261018_0046';report['db_check']='PASS'
    assert db.session.scalar(text('SELECT @@tx_isolation'))==isolation.replace(' ','-')

for scenario in ['clean_csv_21','one_error_51','voluntary_edit']:
    uid,name=owner();client,csrf=login(name)
    payload=table(source()) if scenario=='clean_csv_21' else json.dumps(source(51,True) if scenario=='one_error_51' else source()).encode()
    response=client.post('/nutrition/import',data={'csrf_token':csrf,'file':(io.BytesIO(payload),'QA Issue32.'+('csv' if scenario=='clean_csv_21' else 'json'))})
    assert response.status_code==302;key=response.location.rsplit('/',1)[1];path='/nutrition/import/'+key
    with app.app_context():
        row=imports.owned(uid,key);before=copy.deepcopy(row.review_json);revision=row.revision
        state=review.overview(row)
        assert state['counts']['ready']==(50 if scenario=='one_error_51' else 21)
        assert not any(counts(uid).values())
    if scenario=='one_error_51':
        assert client.post(path+'/decisions',data=dict(revision=revision,edit_index='25',r25_basis_verified='yes',r25_basis_amount='100',r25_basis_unit='g')).status_code==400
        assert client.post(path+'/decisions',data=dict(revision=revision,edit_index='25',r25_basis_verified='yes',r25_basis_amount='100',r25_basis_unit='g',csrf_token=csrf)).status_code==302
        revision+=1
        with app.app_context():
            row=imports.owned(uid,key)
            assert row.review_json['rows'][:25]==before['rows'][:25] and row.review_json['rows'][26:]==before['rows'][26:]
            assert review.overview(row)['counts']['ready']==51
    if scenario=='voluntary_edit':
        old=signed(client,key)
        assert client.post(path+'/decisions',data=dict(revision=revision,edit_index='0',r0_amount='150',csrf_token=csrf)).status_code==302;revision+=1
        assert client.post(path+'/confirm',data=dict(revision=revision-1,token=old,consent_consumed='yes',csrf_token=csrf)).status_code==409
        assert client.post(path+'/decisions',data=dict(revision=revision,edit_index='0',r0_contribution_protein='11',csrf_token=csrf)).status_code==302;revision+=1
        assert client.get(path+'?edit=1&panel=quantity').status_code==200
        assert client.get(path).status_code==200
        with app.app_context():
            row=imports.owned(uid,key)
            assert row.review_json['rows'][1:]==before['rows'][1:] and not any(counts(uid).values())
    def no_writes(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    with app.app_context():engine=db.engine
    event.listen(engine,'before_cursor_execute',no_writes)
    try:
        assert client.get(path).status_code==200
        assert client.get(path+'?edit=0&panel=nutrition').status_code==200
    finally:event.remove(engine,'before_cursor_execute',no_writes)
    token=signed(client,key);fields=dict(revision=revision,token=token,csrf_token=csrf,consent_consumed='yes')
    assert client.post(path+'/confirm',data=dict(fields,token=token+'bad')).status_code==409
    assert client.post(path+'/confirm',data=dict(fields,consent_consumed='')).status_code==422
    original=imports.apply_document
    def fail_after_flush(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('QA only forced rollback')
    with patch.object(imports,'apply_document',fail_after_flush):assert client.post(path+'/confirm',data=fields).status_code==409
    with app.app_context():assert not any(counts(uid).values())
    assert client.post(path+'/confirm',data=fields).status_code==200
    assert client.post(path+'/confirm',data=fields).status_code==200
    otherid,othername=owner();other,othercsrf=login(othername)
    assert other.get(path).status_code==404
    assert other.post(path+'/decisions',data=dict(revision=revision,edit_index='0',r0_amount='999',csrf_token=othercsrf,user_id=uid)).status_code==404
    with app.app_context():
        actual=counts(uid);expected=51 if scenario=='one_error_51' else 21
        assert actual==dict(meal_logs=expected,food_products=0,nutrition_import_receipts=1),actual
        logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid).order_by(MealLog.id)).all()
        if scenario=='voluntary_edit':
            assert Decimal(logs[0].snapshot_json['summary']['energy']['value'])==300
            assert Decimal(logs[0].snapshot_json['summary']['protein']['value'])==11
        snapshots=[semantic_snapshot(log.snapshot_json) for log in logs]
        payload=build_user_data_document(db.session.get(User,uid),uid)
        service=AccountRestoreService();preview=service.preview(payload,user_id=otherid)
        result=service.commit(payload,user_id=otherid,confirmation_token=preview['confirmation_token'])
        assert result['committed'],result
        assert [semantic_snapshot(log['snapshot']) for log in export_bundle(otherid)['logs']]==snapshots
        report['cases'].append(dict(scenario=scenario,records=expected,products=0,receipts=1,
            rollback='PASS',owner_csrf_signature_consent='PASS',export_restore='PASS',get_no_writes='PASS'))

# Same revision edited concurrently: exactly one edit wins and other rows stay.
uid,name=owner()
with app.app_context():
    row=imports.start(uid,json.dumps(source()).encode(),'QA concurrent preview.json');db.session.commit();key=row.public_id;revision=row.revision
barrier=threading.Barrier(2)
def concurrent_edit(amount):
    client,csrf=login(name);barrier.wait(timeout=20)
    return client.post('/nutrition/import/'+key+'/decisions',data=dict(revision=revision,edit_index='0',r0_amount=amount,csrf_token=csrf)).status_code
with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(concurrent_edit,['150','200']))
assert sorted(statuses)==[302,409],statuses
barrier=threading.Barrier(2)
def concurrent_save(_):
    client,csrf=login(name);token=signed(client,key)
    with app.app_context():current=imports.owned(uid,key).revision
    barrier.wait(timeout=20)
    return client.post('/nutrition/import/'+key+'/confirm',data=dict(revision=current,token=token,csrf_token=csrf,consent_consumed='yes')).status_code
with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(concurrent_save,range(2)))
assert 200 in statuses and set(statuses)<={200,409},statuses
with app.app_context():
    assert counts(uid)==dict(meal_logs=21,food_products=0,nutrition_import_receipts=1)
report['concurrent_edit']=sorted([302,409]);report['concurrent_save']=statuses
report['prior_reprocess']=[]
for version,sha in [('29','1cf8d830ba801a8c8121cf594b07a0269a6d6e6f'),('30','12bad71a60b96b57d282cfaf745fc0dc4ed27ab6'),('31','c9cbb86b7b558d6b8c1e838e64966e2a48700bd9')]:
    modules={}
    for kind,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py')]:
        code=subprocess.check_output(['git','show',sha+':'+path],cwd=ROOT)
        module=types.ModuleType('qa_maria_prior_'+kind);exec(compile(code,sha+'/'+path,'exec'),module.__dict__);modules[kind]=module
    service=modules['service'];service.extract=modules['parser'].extract
    service.EXTRACTOR_VERSION=getattr(modules['parser'],'EXTRACTOR_VERSION','nutrition-import-v1')
    for expired in [False,True]:
        uid,name=owner();client,csrf=login(name)
        with app.app_context():
            payload=(ROOT/'examples/qa/nutrition-import-ux/legacy-daily-semantic-21.json').read_bytes()
            old=service.start(uid,payload,'QA exact prior'+version+'.json')
            service.update(uid,old.public_id,old.revision,'destination',dict(destination='consumed',name='QA prior consumed file'))
            service.update(uid,old.public_id,old.revision,'fields',dict(index='1',_section='identity',name='QA kept prior name',date='2026-01-15',meal_type='breakfast'))
            service.update(uid,old.public_id,old.revision,'fields',dict(index='1',_section='composition',amount='180',unit=old.review_json['rows'][1]['unit']))
            if expired:old.created_at-=timedelta(days=2)
            db.session.commit();oldkey=old.public_id;oldrevision=old.revision;frozen=copy.deepcopy(old.review_json);oldcreated=old.created_at
        fields=dict(revision=oldrevision,csrf_token=csrf)
        response=client.post('/nutrition/import/'+oldkey+'/reprocess',data=fields);assert response.status_code==302
        freshkey=response.location.rsplit('/',1)[1];freshpath='/nutrition/import/'+freshkey
        with app.app_context():
            fresh=imports.owned(uid,freshkey);rev=fresh.revision
            assert fresh.review_json['rows'][1]['name']=='QA kept prior name' and fresh.review_json['rows'][1]['amount']=='180'
            assert imports.owned(uid,oldkey).review_json==frozen
        assert client.post(freshpath+'/decisions',data=dict(revision=rev,csrf_token=csrf,edit_index='2',r2_name='QA new fork correction')).status_code==302
        assert client.post('/nutrition/import/'+oldkey+'/reprocess',data=fields).location==response.location
        with app.app_context():
            fresh=imports.owned(uid,freshkey);rev=fresh.revision
            assert fresh.review_json['rows'][2]['name']=='QA new fork correction'
            assert not any(counts(uid).values())
        response=client.post(freshpath+'/decisions',data=dict(revision=rev,csrf_token=csrf,accept_previous='yes',accept_legacy_totals='yes',
            use_declarations='yes',r1_interpretation='source_total',r10_interpretation='consumed_total',r11_nutrient_fiber_action='unknown'))
        assert response.status_code==302,(version,expired,response.status_code,re.findall(r'role="(?:status|alert)">([^<]+)',response.text))
        with app.app_context():
            fresh=imports.owned(uid,freshkey);rev=fresh.revision;state=review.overview(fresh)
            assert state['counts']['ready']==21,state['counts']
        assert client.post(freshpath+'/confirm',data=dict(revision=rev,csrf_token=csrf,token=signed(client,freshkey),consent_consumed='yes')).status_code==200
        with app.app_context():
            assert counts(uid)==dict(meal_logs=21,food_products=0,nutrition_import_receipts=1)
            old=imports.owned(uid,oldkey);assert old.review_json==frozen and old.created_at==oldcreated
        report['prior_reprocess'].append(dict(version=version,expired=expired,previous_unchanged=True,records=21,products=0,receipts=1))
out=ROOT/'design/nutrition-import-preview/qa';out.mkdir(parents=True,exist_ok=True)
(out/('mariadb-'+isolation.replace(' ','_')+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
