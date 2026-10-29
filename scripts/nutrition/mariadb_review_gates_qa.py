"""Two review gates only. Synthetic LOCAL MariaDB QA 0046, no NAS access."""
import copy,json,os,re,sys,tempfile,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from html import unescape
from pathlib import Path
from sqlalchemy import event,text
from flask_migrate import check
from app import create_app
from app.extensions import db
from app.models import User,FoodCatalogSource,MealLog,FoodProduct,NutritionImportReceipt
from app.services import food_catalog as catalog,nutrition_import as imports,nutrition_import_review as compact
sys.path.insert(0,'/qa/scripts/nutrition')
from qa_legacy_import_29 import legacy_review,SHA

root=Path(tempfile.mkdtemp(prefix='qa-review-gates-maria-'))
app=create_app({'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads/raw','GENERATED_UPLOAD_ROOT':root/'generated',
 'PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,
 'SQLALCHEMY_ENGINE_OPTIONS':{'pool_pre_ping':True,'isolation_level':os.environ.get('QA_ISOLATION','READ COMMITTED')}})
fixture=Path('/qa/examples/qa/nutrition-import-ux');report={'status':'PASS','data':'fictional LOCAL QA only','legacy_code_sha':SHA,'cases':[]}


class Client:
 def __init__(self):self.client=app.test_client()
 def get(self,*args,**kwargs):
  with app.app_context():return self.client.get(*args,**kwargs)
 def post(self,*args,**kwargs):
  with app.app_context():return self.client.post(*args,**kwargs)


def login(name):
 client=Client();page=client.get('/login');csrf=unescape(re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page.text)[1])
 assert client.post('/login',data={'username':name,'password':'fictional-review-gates-password','csrf_token':csrf}).status_code==302
 return client,csrf


def count(model,owner):return db.session.scalar(db.select(db.func.count(model.id)).where(model.user_id==owner))


with app.app_context():
 assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
 assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
 check(directory='/app/migrations');report['isolation']=db.session.scalar(text('SELECT @@tx_isolation'))
 if not db.session.get(FoodCatalogSource,'qa_import_consumed'):
  catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text()));catalog.activate('qa_import_consumed','1',1);db.session.commit()

for expired in [False,True]:
 with app.app_context():
  name='QA legacy gate '+uuid.uuid4().hex[:12];owner=User(username=name,role='user',timezone='America/Mexico_City')
  owner.set_password('fictional-review-gates-password');db.session.add(owner);db.session.commit();uid=owner.id
  ref=next(h['ref'] for h in catalog.search(uid,source='qa_import_consumed') if h['source_food_id']=='1')
  payload=(fixture/'consumed-text-portions-21.json').read_bytes();old=legacy_review(uid,payload,ref)
  if expired:old.created_at-=timedelta(days=2);db.session.commit()
  key=old.public_id;frozen=copy.deepcopy(old.review_json);source=copy.deepcopy(old.source_json);created=old.created_at
  assert compact.overview(old)['counts']['ready']==1
  assert imports.start(uid,payload,'QA reupload retained.json').id==old.id;db.session.commit()
 client,csrf=login(name)
 with app.app_context():
  def guard(conn,cursor,stmt,params,context,many):
   assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
  event.listen(db.engine,'before_cursor_execute',guard)
  try:
   page=client.get('/nutrition/import/'+key);assert page.status_code==200 and 'Reprocesar original con importador actualizado' in page.text
  finally:event.remove(db.engine,'before_cursor_execute',guard)
 path='/nutrition/import/'+key+('/recover' if expired else '/reprocess')
 assert client.post(path,data={'revision':5}).status_code==400
 assert client.post(path,data={'revision':6,'csrf_token':csrf}).status_code==409
 # Concurrent forks must converge on one independently editable new draft.
 barrier=threading.Barrier(2)
 def fork(_):
  c,token=login(name);barrier.wait(timeout=20)
  r=c.post(path,data={'revision':5,'csrf_token':token});assert r.status_code==302
  return r.location
 with ThreadPoolExecutor(max_workers=2) as pool:locations=list(pool.map(fork,range(2)))
 assert locations[0]==locations[1]
 newkey=locations[0].rsplit('/',1)[1]
 with app.app_context():
  fresh=imports.owned(uid,newkey);revision=fresh.revision
  assert fresh.source_json['reprocess_pending'] and fresh.source_json['reprocessed_revision']==5
  assert fresh.review_json['rows'][1]['name']=='QA nombre corregido por usuario'
  assert fresh.review_json['rows'][2]['amount']=='150'
  assert imports.start(uid,payload,'QA resume updated.json').id==fresh.id;db.session.commit()
 assert client.post('/nutrition/import/'+newkey+'/decisions',data={'revision':revision,'csrf_token':csrf,'r3_name':'QA edición posterior nueva'}).status_code==302
 assert client.post(path,data={'revision':5,'csrf_token':csrf}).location==locations[0]
 with app.app_context():
  fresh=imports.owned(uid,newkey);assert fresh.review_json['rows'][3]['name']=='QA edición posterior nueva';revision=fresh.revision
 values={'revision':revision,'csrf_token':csrf,'accept_previous':'yes','use_declarations':'yes','r9_portion_label_confirmed':'yes',
         **{f'r{i}_equivalence_confirmed':'yes' for i in [4,5,6,7,8,10,11]}}
 assert client.post('/nutrition/import/'+newkey+'/decisions',data=values).status_code==302
 page=client.get('/nutrition/import/'+newkey);assert page.status_code==200
 signed=unescape(re.search(r'name="token" value="([^"]+)"',page.text)[1]);assert signed
 with app.app_context():revision=imports.owned(uid,newkey).revision
 data={'revision':revision,'csrf_token':csrf,'token':signed,'consent_consumed':'yes'}
 assert client.post('/nutrition/import/'+newkey+'/confirm',data=data).status_code==200
 assert client.post('/nutrition/import/'+newkey+'/confirm',data=data).status_code==200
 with app.app_context():
  assert count(MealLog,uid)==21 and count(FoodProduct,uid)==0 and count(NutritionImportReceipt,uid)==1
  old=imports.owned(uid,key)
  assert old.review_json==frozen and old.source_json==source and old.created_at==created and old.revision==5
  logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid)).all()
  assert sum(Decimal(log.snapshot_json['summary']['energy']['value']) for log in logs)==Decimal('4042.79')
  assert all(log.timezone=='America/Mexico_City' for log in logs)
  assert any(log.snapshot_json['name']=='QA nombre corregido por usuario' for log in logs)
  assert next(log for log in logs if log.snapshot_json['name']=='QA cereal porciones sin masa').snapshot_json['summary']['energy']['total_weight'] is None
  report['cases'].append({'expired':expired,'legacy_revision':5,'initial_ready':1,'initial_pending':20,'saved':21,'products':0,
   'previous_review_unchanged':True,'reupload_preserves_decisions':True,'concurrent_reprocess_same_review':True,
   'independently_edited_new_review_preserved':True,'equivalence_verifications':7,'portion_base_verification':1,
   'GET_DML_DDL':0,'replay_no_duplicates':True,'totals_kcal':'4042.79'})
report.update(alembic='20261018_0046',db_check='PASS',new_DDL=False,production_access=False)
out=Path('/evidence')/('review-gates-mariadb-'+os.environ.get('QA_ISOLATION','READ COMMITTED').replace(' ','_')+'.json')
out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
