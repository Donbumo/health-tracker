"""Fictional legacy semantic regression on an isolated MariaDB 0046 schema.

Run only against the disposable nutrition_legacy_qa schema. Prior parser/service
blobs, checked out from Git, are supplied via QA_PRIOR_CODE (29/ and 30/).
"""
import copy,json,os,re,sys,tempfile,threading,types,uuid
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
from app.services.nutrition_math import NutritionError
root=Path(tempfile.mkdtemp(prefix='qa-legacy-semantics-'))
app=create_app({'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads/raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable',
 'NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,
 'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':os.environ['QA_ISOLATION'],'pool_pre_ping':True}})
fixture=Path('/qa/examples/qa/nutrition-import-ux');report={'status':'PASS','fixture':'fictional legacy structure 21 / 20 missing bases','cases':[]}


def login(name):
 c=app.test_client();p=c.get('/login');csrf=unescape(re.search(r'name="csrf_token"[^>]*value="([^"]+)"',p.text)[1])
 assert c.post('/login',data={'username':name,'password':'fictional-semantic-password','csrf_token':csrf}).status_code==302
 return c,csrf


def prior_service(version):
 modules={}
 for name in ['nutrition_sources.py','nutrition_import.py']:
  path=Path(os.environ['QA_PRIOR_CODE'])/version/name
  code=path.read_bytes();module=types.ModuleType('qa_prior_'+name[:-3]);exec(compile(code,str(path),'exec'),module.__dict__);modules[name]=module
 service=modules['nutrition_import.py'];parser=modules['nutrition_sources.py'];service.extract=parser.extract
 if hasattr(parser,'EXTRACTOR_VERSION'):service.EXTRACTOR_VERSION=parser.EXTRACTOR_VERSION
 return service


with app.app_context():
 assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_legacy_qa'
 assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
 check(directory='/app/migrations');report['isolation']=db.session.scalar(text('SELECT @@tx_isolation'))
 if not db.session.get(FoodCatalogSource,'qa_import_consumed'):
  catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text()));catalog.activate('qa_import_consumed','1',1);db.session.commit()

for version in ['29','30']:
 for expired in [False,True]:
  with app.app_context():
   owner=User(username='QA semantic '+uuid.uuid4().hex[:12],role='user',timezone='America/Mexico_City');owner.set_password('fictional-semantic-password')
   db.session.add(owner);db.session.commit();uid=owner.id;name=owner.username
   ref=next(h['ref'] for h in catalog.search(uid,source='qa_import_consumed') if h['source_food_id']=='1')
   service=prior_service(version);old=service.start(uid,(fixture/'legacy-daily-semantic-21.json').read_bytes(),'QA prior daily.json')
   service.update(uid,old.public_id,old.revision,'destination',{'destination':'consumed','name':'QA prior technical review'})
   service.update(uid,old.public_id,old.revision,'bind',{'index':'0','ref':ref,'food_revision':'1','amount':'120','unit':'g'})
   assert compact.overview(old)['counts']['ready']==1 and compact.overview(old)['counts']['decision']==20
   service.update(uid,old.public_id,old.revision,'fields',{'index':'1','_section':'identity','name':'QA retained name','date':'2026-01-15','meal_type':'breakfast'})
   service.update(uid,old.public_id,old.revision,'fields',{'index':'1','_section':'composition','amount':'180','unit':'ml'})
   if expired:old.created_at-=timedelta(days=2)
   db.session.commit();key=old.public_id;revision=old.revision;frozen=copy.deepcopy(old.review_json);source=copy.deepcopy(old.source_json);created=old.created_at
  path='/nutrition/import/'+key+('/recover' if expired else '/reprocess')
  c,csrf=login(name)
  assert c.post(path,data={'revision':revision}).status_code==400
  barrier=threading.Barrier(2)
  def fork(_):
   client,token=login(name);barrier.wait(timeout=20)
   r=client.post(path,data={'revision':revision,'csrf_token':token});assert r.status_code==302,(version,expired,r.status_code,re.findall(r'<p[^>]*>([^<]{1,500})</p>',r.text))
   return r.location
  with ThreadPoolExecutor(max_workers=2) as pool:locations=list(pool.map(fork,range(2)))
  assert locations[0]==locations[1];newkey=locations[0].rsplit('/',1)[1]
  with app.app_context():
   fresh=imports.owned(uid,newkey);rev=fresh.revision
   assert fresh.review_json['rows'][1]['name']=='QA retained name' and fresh.review_json['rows'][1]['amount']=='180'
   assert fresh.review_json['rows'][1]['basis_amount']=='121'
  # Consecutive POSTs: an accepted consumed_total cannot outlive a quantity edit.
  assert c.post('/nutrition/import/'+newkey+'/decisions',data={'revision':rev,'csrf_token':csrf,'r1_interpretation':'consumed_total'}).status_code==302
  with app.app_context():rev=imports.owned(uid,newkey).revision
  assert c.post('/nutrition/import/'+newkey+'/decisions',data={'revision':rev,'csrf_token':csrf,'r1_amount':'190'}).status_code==302
  with app.app_context():
   changed=imports.owned(uid,newkey);rev=changed.revision
   assert changed.review_json['rows'][1]['basis_interpretation']['status']=='proposed'
   assert compact.overview(changed)['records'][1]['state']=='decision'
  data={'revision':rev,'csrf_token':csrf,'r2_amount':'2','accept_previous':'yes','accept_legacy_totals':'yes','use_declarations':'yes',
    'r1_interpretation':'source_total','r10_interpretation':'consumed_total','r11_nutrient_fiber_action':'unknown'}
  assert c.post('/nutrition/import/'+newkey+'/decisions',data=data).status_code==302
  assert c.post(path,data={'revision':revision,'csrf_token':csrf}).location==locations[0]
  with app.app_context():
   changed=imports.owned(uid,newkey);rev=changed.revision;view=compact.overview(changed)
   assert view['counts']['ready']==20 and view['counts']['decision']==1,view['counts']
   assert changed.review_json['rows'][2]['basis_interpretation']['status']=='proposed'
  assert c.post('/nutrition/import/'+newkey+'/decisions',data={'revision':rev,'csrf_token':csrf,'r2_interpretation':'consumed_total'}).status_code==302
  with app.app_context():
   fresh=imports.owned(uid,newkey);view=compact.overview(fresh);assert view['counts']['ready']==21,[(r['index'],r['issues']) for r in view['records'] if r['issues']]
   document=compact.document(fresh);rev=fresh.revision
   expected=sum((Decimal(e['declaration']['nutrients']['energy']['value'])*Decimal(e['portion_amount'])/Decimal(e['declaration']['basis_amount']) for e in document['data']['entries']),Decimal(0))
   def no_writes(conn,cursor,stmt,params,context,many):
    assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','REPLACE'}
   event.listen(db.engine,'before_cursor_execute',no_writes)
   try:
    page=c.get('/nutrition/import/'+newkey);assert page.status_code==200
   finally:event.remove(db.engine,'before_cursor_execute',no_writes)
  signed=unescape(re.search(r'name="token" value="([^"]+)"',page.text)[1]);assert signed
  data={'revision':rev,'csrf_token':csrf,'token':signed}
  assert c.post('/nutrition/import/'+newkey+'/confirm',data=data).status_code==422
  data['consent_consumed']='yes'
  barrier=threading.Barrier(2)
  def confirm(_):
   client,token=login(name);barrier.wait(timeout=20)
   response=client.post('/nutrition/import/'+newkey+'/confirm',data=dict(data,csrf_token=token))
   return response.status_code,re.findall(r'<p[^>]*>([^<]{1,500})</p>',response.text) if response.status_code!=200 else []
  with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(confirm,range(2)))
  assert 200 in [c[0] for c in codes] and all(c[0] in {200,409} for c in codes),codes
  assert c.post('/nutrition/import/'+newkey+'/confirm',data=data).status_code==200
  with app.app_context():
   logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid)).all()
   assert len(logs)==21 and db.session.scalar(db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id==uid))==0
   assert db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==uid))==1
   # finite_source_number deliberately rounds each contribution to 12 decimals.
   total=sum(Decimal(l.snapshot_json['summary']['energy']['value']) for l in logs)
   assert abs(total-expected)<Decimal('0.000000000002')
   old=imports.owned(uid,key);assert old.review_json==frozen and old.source_json==source and old.created_at==created
   assert all(l.timezone=='America/Mexico_City' for l in logs)
   report['cases'].append(dict(version=version,expired=expired,before_ready=1,before_pending=20,after_ready=21,after_pending=0,
     stale_interpretation_invalidated=True,group_edit_excluded_one_and_kept_others=True,products=0,receipts=1,concurrent_fork_and_confirm=True,concurrent_confirm_statuses=[c[0] for c in codes],retry_status=200,old_unchanged=True,GET_DML_DDL=0,quantity_correction_preserved=True))
report.update(alembic='20261018_0046',db_check='PASS',production_access=False,new_migrations=False)
Path('/evidence', 'legacy-mariadb-'+os.environ['QA_ISOLATION'].replace(' ','_')+'.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
