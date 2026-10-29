"""LOCAL synthetic QA 0046, no upgrade/stamp/reset or production connections."""
import copy,hashlib,json,os,re,tempfile,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from html import unescape
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event,text
from flask_migrate import check
from app import create_app
from app.extensions import db
from app.models import User,MealLog,FoodProduct,DailyNutrition,NutritionImportReceipt,FoodCatalogSource
from app.services import food_catalog as catalog,nutrition_import as imports,nutrition_import_review as compact,nutrition_intelligence as ni
from app.services.nutrition_math import NutritionError

root=Path(tempfile.mkdtemp(prefix='qa-consumed-21-maria-'))
app=create_app({'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads'/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,'SQLALCHEMY_ENGINE_OPTIONS':{'pool_pre_ping':True,'isolation_level':os.environ.get('QA_ISOLATION','READ COMMITTED')}})
fixture=Path('/qa/examples/qa/nutrition-import-ux')
report={'status':'PASS','data':'fictional isolated LOCAL MariaDB only','production_access':False}


class Client:
    def __init__(self):self.client=app.test_client()
    def get(self,*args,**kwargs):
        with app.app_context():return self.client.get(*args,**kwargs)
    def post(self,*args,**kwargs):
        with app.app_context():return self.client.post(*args,**kwargs)


def login(name):
    client=Client();page=client.get('/login')
    csrf=unescape(re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page.text)[1])
    assert client.post('/login',data={'username':name,'password':'fictional-consumed-password','csrf_token':csrf}).status_code==302
    return client,csrf


def token(client,key):
    page=client.get('/nutrition/import/'+key);assert page.status_code==200
    return unescape(re.search(r'name="token" value="([^"]+)"',page.text)[1])


def count(model,uid):return db.session.scalar(db.select(db.func.count(model.id)).where(model.user_id==uid))


with app.app_context():
    assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
    assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
    check(directory='/app/migrations');report['isolation']=db.session.scalar(text('SELECT @@tx_isolation'))
    if not db.session.get(FoodCatalogSource,'qa_import_consumed'):
        catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text()))
        catalog.activate('qa_import_consumed','1',1);db.session.commit()
    suffix=uuid.uuid4().hex[:12]
    owners=[]
    for label in ['main','other']:
        owner=User(username='QA consumed '+label+' '+suffix,role='user',timezone='America/Mexico_City')
        owner.set_password('fictional-consumed-password');db.session.add(owner);owners.append(owner)
    db.session.commit();uid=owners[0].id;name=owners[0].username;othername=owners[1].username;otherid=owners[1].id
    payload=(fixture/'consumed-21.json').read_bytes()
    row=imports.start(uid,payload,'QA consumed-21.json');db.session.commit();key=row.public_id
    assert compact.overview(row)['counts']==dict(ready=1,decision=20,invalid=0,omitted=0)
    # A historical snapshot and a same-date legacy aggregate are both preserved.
    from app.services.importers.standard_import_executor import StandardImportExecutor
    history=copy.deepcopy(json.loads(payload));history['records']=history['records'][:1];history['records'][0]['date']='2026-10-25'
    previous=imports.start(uid,json.dumps(history).encode(),'QA historical prior.json');db.session.commit()
    assert StandardImportExecutor().commit_documents([compact.document(previous)],user_id=uid,target_type='nutrition_import',confirmed=True)['committed']
    historical=db.session.scalar(db.select(MealLog).where(MealLog.user_id==uid));frozen=copy.deepcopy(historical.snapshot_json)
    db.session.add(DailyNutrition(user_id=uid,date=date(2026,10,26),source='qa',calories=200));db.session.commit()
    client,csrf=login(name);other,othercsrf=login(othername)
    def guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    event.listen(db.engine,'before_cursor_execute',guard)
    try:
        page=client.get('/nutrition/import/'+key+'?r1_p-1_query=pollo&r2_p-1_query=arroz')
        assert page.status_code==200 and page.headers['Cache-Control']=='private, no-store'
        assert other.get('/nutrition/import/'+key).status_code==404
    finally:event.remove(db.engine,'before_cursor_execute',guard)
    assert client.post('/nutrition/import/'+key+'/decisions',data={'revision':row.revision,'use_declarations':'yes'}).status_code==400
    refs={h['source_food_id']:h['ref'] for h in catalog.search(uid,source='qa_import_consumed')}
    values={'revision':row.revision,'csrf_token':csrf,'use_declarations':'yes','r6_resolution':'private',
            'r1_p-1_ref':refs['2'],'r1_p-1_amount':'100','r1_p-1_unit':'g'}
    values.update({f'r{i}_equivalence_confirmed':'yes' for i in [4,5,6,7,8]})
    assert client.post('/nutrition/import/'+key+'/decisions',data=values).status_code==302
    db.session.rollback();db.session.expire_all()
    assert compact.overview(row)['counts']['decision']==21  # Existing date must be reviewed.
    assert count(FoodProduct,uid)==0 and count(MealLog,uid)==1
    assert client.post('/nutrition/import/'+key+'/decisions',data={'revision':row.revision,'csrf_token':csrf,'day_2026-10-26_conflict_action':'keep_and_add','day_2026-10-26_authority':'disjoint_aggregate'}).status_code==302
    db.session.rollback();db.session.expire_all()
    assert compact.overview(row)['counts']['ready']==21
    document=compact.document(row);expected=sum((Decimal(imports.meal_snapshot(e,imports.resolved_entries(e,uid),'America/Mexico_City')['summary']['energy']['value']) for e in document['data']['entries']),Decimal(0))
    canonical_review=imports.start(uid,json.dumps(document).encode(),'QA canonical consumed-21.json');db.session.commit()
    assert compact.overview(canonical_review)['counts']['ready']==21
    assert len(compact.document(canonical_review)['data']['entries'])==21
    signed=token(client,key);revision=row.revision
    data={'revision':revision,'token':signed,'csrf_token':csrf,'consent_consumed':'yes'}
    assert client.post('/nutrition/import/'+key+'/confirm',data=dict(data,token=signed+'x')).status_code==409
    assert client.post('/nutrition/import/'+key+'/confirm',data=dict(data,consent_consumed='')).status_code==422
    assert other.post('/nutrition/import/'+key+'/confirm',data=dict(data,csrf_token=othercsrf)).status_code==404
    actual=ni.confirm
    def fail(*args,**kwargs):
        result=actual(*args,**kwargs)
        if count(FoodProduct,uid):raise NutritionError('QA induced rollback after product and consumption flush')
        return result
    with patch.object(ni,'confirm',side_effect=fail):
        assert client.post('/nutrition/import/'+key+'/confirm',data=data).status_code==409
    db.session.rollback();db.session.expire_all()
    assert count(MealLog,uid)==1 and count(FoodProduct,uid)==0 and count(NutritionImportReceipt,uid)==1
    assert imports.owned(uid,key).state=='pending'
    db.session.rollback()

barrier=threading.Barrier(2)
def concurrent(_):
    client,csrf=login(name);signed=token(client,key);barrier.wait(timeout=20)
    return client.post('/nutrition/import/'+key+'/confirm',data={'revision':revision,'token':signed,'csrf_token':csrf,'consent_consumed':'yes'}).status_code
with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(concurrent,range(2)))
assert 200 in statuses and set(statuses)<={200,409},statuses

with app.app_context():
    assert count(MealLog,uid)==22 and count(FoodProduct,uid)==1 and count(NutritionImportReceipt,uid)==2
    historical=db.session.scalar(db.select(MealLog).where(MealLog.user_id==uid,MealLog.local_date==date(2026,10,25)))
    assert historical.snapshot_json==frozen
    logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid,MealLog.local_date==date(2026,10,26))).all()
    assert len(logs)==21 and sum(Decimal(log.snapshot_json['summary']['energy']['value']) for log in logs)==expected
    day=db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id==uid,DailyNutrition.date==date(2026,10,26)))
    assert day.calories==expected+200 and day.authority_baseline_json['original_totals']['calories']=='200.000'
    byname={log.snapshot_json['name']:log.snapshot_json for log in logs}
    assert Decimal(byname['QA bebida en dos latas Marca Inventada']['summary']['energy']['value'])==Decimal('993.3')
    assert Decimal(byname['QA barra Amaranto MX']['summary']['energy']['value'])==Decimal('47.7')
    assert byname['QA cereal porciones sin masa']['summary']['energy']['total_weight'] is None
    assert byname['QA queso panela']['declared_nutrition']['nutrients']['iron']['state']=='trace'
    assert byname['QA queso panela']['declared_nutrition']['nutrients']['sodium']['state']=='below_limit'
    receipt=db.session.scalar(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==uid,NutritionImportReceipt.source_sha256==hashlib.sha256(payload).hexdigest()))
    assert receipt and receipt.result_json['logs']==21
    assert imports.start(uid,payload,'QA replay bytes.json').state=='completed';db.session.commit()
    # Canonical export and isolated restore preserve bindingless declarations.
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle
    bundle=export_bundle(uid);target=otherid
    payload=build_user_data_document(db.session.get(User,uid),uid)
    service=AccountRestoreService();preview=service.preview(payload,user_id=target)
    result=service.commit(payload,user_id=target,confirmation_token=preview['confirmation_token']);assert result['committed'],result
    restored=export_bundle(target)
    from app.services.nutrition_portability import semantic_snapshot
    assert [semantic_snapshot(log['snapshot']) for log in restored['logs']]==[semantic_snapshot(log['snapshot']) for log in bundle['logs']]
    report.update(alembic='20261018_0046',db_check='PASS',detected=21,initial_ready=1,initial_decision=20,saved=21,
                  existing_candidate_bindings=2,private_products=1,declared_without_catalog=18,GET_DML_DDL=0,
                  owner_CSRF_signature_consent='PASS',legacy_date_explicit_decision='PASS',historical_snapshot_unchanged=True,
                  original_SHA_retained=True,rollback_after_product_and_log_flush='PASS',concurrent_statuses=statuses,
                  replay_no_duplicates=True,canonical_JSON_review='PASS',export_restore='PASS',massless_portion=True,totals_kcal=str(expected),new_DDL=False)
out=Path('/evidence')/('consumed-mariadb-'+os.environ.get('QA_ISOLATION','READ COMMITTED').replace(' ','_')+'.json')
out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
