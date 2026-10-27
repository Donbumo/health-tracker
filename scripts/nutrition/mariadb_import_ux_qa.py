"""Focused existing LOCAL synthetic QA 0046 only; never upgrade/stamp/reset.
Run B runtime with working-tree app read-only at /app/app and fixtures at /qa.
"""
import copy,io,json,re,os,tempfile,uuid,threading
from pathlib import Path
from html import unescape
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from itsdangerous import TimestampSigner
from sqlalchemy import text,event
from flask_migrate import check
from app import create_app
from app.extensions import db
from app.models import User,NutritionPlan,NutritionImportReceipt,NutritionImportDraft,MealLog,FoodProduct,Recipe,FoodCatalogSource
from app.services import food_catalog as catalog,nutrition_import as imports,nutrition_import_review as compact
root=Path(tempfile.mkdtemp(prefix='qa-nutrition-import-maria-'))
app=create_app({'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads'/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,'SQLALCHEMY_ENGINE_OPTIONS':{'pool_pre_ping':True,'isolation_level':os.environ.get('QA_ISOLATION','READ COMMITTED')}})
fixture=Path('/qa/examples/qa/nutrition-import-ux');report={'status':'PASS','data':'fictional isolated LOCAL MariaDB only','new_DDL':False}
class RequestClient:
 def __init__(self):self.client=app.test_client()
 def get(self,*args,**kwargs):
  with app.app_context():return self.client.get(*args,**kwargs)
 def post(self,*args,**kwargs):
  with app.app_context():return self.client.post(*args,**kwargs)
def login(name,password):
 client=RequestClient();r=client.get('/login');csrf=unescape(re.search(r'name="csrf_token"[^>]*value="([^"]+)"',r.text)[1]);response=client.post('/login',data={'username':name,'password':password,'csrf_token':csrf});assert response.status_code==302,('QA login HTTP',response.status_code);return client,csrf
def review_token(client,key):
 r=client.get('/nutrition/import/'+key);assert r.status_code==200;return unescape(re.search(r'name="token" value="([^"]+)"',r.text)[1])
with app.app_context():
 assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
 assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046';check(directory='/app/migrations');report['isolation']=db.session.scalar(text('SELECT @@tx_isolation'))
 if not db.session.get(FoodCatalogSource,'qa_import_ux'):
  catalog.stage(json.loads((fixture/'catalog.json').read_text()));catalog.activate('qa_import_ux','1',1);db.session.commit()
 suffix=uuid.uuid4().hex[:10];password='QA fictional import password'
 owner=User(username='QA import ux '+suffix,role='user');owner.set_password(password);other=User(username='QA other import '+suffix,role='user');other.set_password(password);db.session.add_all([owner,other]);db.session.commit()
 uid=owner.id;username=owner.username;othername=other.username
 payload=(fixture/'mixed-13.json').read_bytes();row=imports.start(uid,payload,'QA mixed-13.json');db.session.commit();key=row.public_id
 assert compact.overview(row)['counts']==dict(ready=10,decision=3,invalid=0,omitted=0)
 refs={h['source_food_id']:h['ref'] for h in catalog.search(uid,source='qa_import_ux')}
 client,csrf=login(username,password)
 statements=[]
 def guard(conn,cursor,stmt,params,context,many):
  operation=stmt.lstrip().split()[0].upper();statements.append(operation);assert operation not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
 event.listen(db.engine,'before_cursor_execute',guard)
 try:
  for url in ['/nutrition/import','/nutrition/import/'+key,'/nutrition/import/'+key+'?q=QA']:
   r=client.get(url);assert r.status_code==200 and r.headers['Cache-Control']=='private, no-store'
 finally:event.remove(db.engine,'before_cursor_execute',guard)
 assert client.post('/nutrition/import/'+key+'/decisions',data={'revision':row.revision}).status_code==400
 # A subset of exception decisions persists, while all domain data remain pending.
 partial={'revision':row.revision,'csrf_token':csrf,'r12_carbohydrate':'unknown','r10_p0_amount':'','r10_p0_unit':'g','r11_p1_ref':'','r11_p1_amount':'100','r11_p1_unit':'g'}
 assert client.post('/nutrition/import/'+key+'/decisions',data=partial).status_code==302
 db.session.rollback();db.session.expire_all()
 assert compact.overview(row)['counts']['ready']==11 and compact.overview(row)['counts']['decision']==2
 assert imports.start(uid,payload,'QA resume partial decisions.json').id==row.id
 db.session.commit()
 from app.models import UploadedFile
 import hashlib
 upload=db.session.get(UploadedFile,row.source_json['upload_id']);original_path=root/upload.storage_path
 original_path.resolve().relative_to(root.resolve())
 assert upload.user_id==uid and upload.sha256==row.source_sha256==hashlib.sha256(original_path.read_bytes()).hexdigest()
 fields={'revision':row.revision,'csrf_token':csrf,'r10_p0_amount':'100','r10_p0_unit':'g','r11_p1_ref':refs['2'],'r11_p1_amount':'100','r11_p1_unit':'g','r12_carbohydrate':'unknown','user_id':other.id}
 assert client.post('/nutrition/import/'+key+'/decisions',data=fields).status_code==302
 db.session.rollback();db.session.expire_all()
 assert compact.overview(row)['counts']['ready']==13
 signed=review_token(client,key);data={'revision':row.revision,'token':signed,'csrf_token':csrf}
 assert client.post('/nutrition/import/'+key+'/confirm',data=dict(data,token=signed+'tampered')).status_code==409
 from app.nutrition.routes import _import_serializer
 claims=_import_serializer().loads(signed)
 moment=TimestampSigner.get_timestamp(None)
 with patch.object(TimestampSigner,'get_timestamp',lambda self:moment-901):expired=_import_serializer().dumps(claims)
 assert client.post('/nutrition/import/'+key+'/confirm',data=dict(data,token=expired)).status_code==409
 otherclient,othercsrf=login(othername,password)
 from flask import g
 g.pop('_login_user',None)
 assert otherclient.get('/nutrition/import/'+key).status_code==404
 assert otherclient.post('/nutrition/import/'+key+'/confirm',data=dict(data,csrf_token=othercsrf)).status_code==404
 g.pop('_login_user',None)
 before={m.__tablename__:db.session.scalar(db.select(db.func.count(m.id)).where(m.user_id==uid)) for m in [FoodProduct,Recipe,MealLog]}
 original=imports.apply_document
 def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('QA induced failure')
 with patch.object(imports,'apply_document',fail):
  assert client.post('/nutrition/import/'+key+'/confirm',data=data).status_code==409
 db.session.rollback();db.session.expire_all();assert row.state=='pending'
 assert not db.session.scalar(db.select(db.func.count(NutritionPlan.id)).where(NutritionPlan.user_id==uid))
 assert not db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==uid))
 assert client.post('/nutrition/import/'+key+'/confirm',data=data).status_code==200
 db.session.rollback();db.session.expire_all();assert row.state=='completed'
 plan=db.session.scalar(db.select(NutritionPlan).where(NutritionPlan.user_id==uid));assert len(plan.snapshot_json['meals'])==13
 assert client.post('/nutrition/import/'+key+'/confirm',data=data).status_code==200
 assert before=={m.__tablename__:db.session.scalar(db.select(db.func.count(m.id)).where(m.user_id==uid)) for m in [FoodProduct,Recipe,MealLog]}
 # Reupload completed file: no new records, authoritative receipt in result GET.
 response=client.post('/nutrition/import',data={'csrf_token':csrf,'file':(io.BytesIO(payload),'QA same bytes.json')});assert response.status_code==302
 assert client.get(response.location).status_code==200
 # Concurrent requests for one normal ten-record file, both signed before POST.
 row2=imports.start(uid,(fixture/'normal-10.json').read_bytes(),'QA concurrent normal-10.json');db.session.commit();key2=row2.public_id;revision2=row2.revision
 db.session.rollback()
barrier=threading.Barrier(2)
def concurrent(_):
 c,csrf=login(username,password);signed=review_token(c,key2);barrier.wait(timeout=15)
 return c.post('/nutrition/import/'+key2+'/confirm',data={'revision':revision2,'token':signed,'csrf_token':csrf}).status_code
with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(concurrent,range(2)))
assert 200 in statuses and set(statuses)<={200,409},statuses
with app.app_context():
 assert db.session.scalar(db.select(db.func.count(NutritionPlan.id)).where(NutritionPlan.user_id==uid))==2
 assert db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==uid))==2
 assert imports.owned(uid,key2).state=='completed'
 report.update(alembic='20261018_0046',db_check='PASS',GET_DML_DDL=0,initial_ready=10,initial_decisions=3,one_exception_POST='PASS',global_confirm='PASS',csrf_signature_expiry_owner='PASS',pending_completion_atomic='PASS',rollback_after_domain_flush='PASS',replay_reupload='PASS',concurrent_statuses=statuses,concurrent_no_duplicates=True,FoodProduct_MealLog_Recipe_unchanged=True,partial_import_enabled=False,partial_review_decisions_resume=True,original_SHA256_retained=True)
out=Path('/evidence')/('mariadb-'+os.environ.get('QA_ISOLATION','READ COMMITTED').replace(' ','_')+'.json');out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
