import json,uuid,hashlib,copy,concurrent.futures,threading
from pathlib import Path
from datetime import date
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.extensions import db
from app.models import User,DailyEnergy,UploadedFile
from app.services.importers.daily_energy import import_daily_energy_file,DailyEnergyImportError
from app.services.importers.standard_import_executor import StandardImportExecutor
from app.services import mobile_health
from app.services.daily_balance import effective_energy_record
from app.services.dashboard.nutrition import effective_energy_value
SCHEMA='nutrition_intelligence_qa_20261009'
report={'baseline':'500589bbafa6d730536595cb7d115f72ebdfe462','scope':'synthetic QA only','isolations':{}}
def document(uid,day,source,**values):
 return {'schema_version':'1.0','record_type':'daily_energy','user_id':uid,'source_type':'uploaded','data':{'date':day,'source':source,**values}}
def upload(doc):
 raw=json.dumps(doc).encode();name=uuid.uuid4().hex+'.json';Path('/tmp/energy18/'+name).write_bytes(raw)
 f=UploadedFile(user_id=doc['user_id'],original_filename='QA-'+name,stored_filename=name,storage_path=name,source_type='uploaded',sha256=hashlib.sha256(raw+name.encode()).hexdigest(),size_bytes=len(raw))
 db.session.add(f);db.session.commit();return f
for level in ['READ COMMITTED','REPEATABLE READ']:
 app=create_app({'DATA_ROOT':Path('/tmp/energy18'),'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':level,'pool_pre_ping':True},'TESTING':True,'WTF_CSRF_ENABLED':False})
 Path('/tmp/energy18').mkdir(exist_ok=True)
 with app.app_context():
  assert db.session.scalar(text('SELECT DATABASE()'))==SCHEMA
  assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
  assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261013_0045'
  user=User(username='QA-energy18-'+uuid.uuid4().hex,role='user');user.set_password('fictional-QA-password');db.session.add(user);db.session.commit();uid=user.id
  cases={}
  partial=document(uid,'2040-01-01','qa_steps',steps=1200,distance_meters=800)
  first,_=import_daily_energy_file(upload(partial),uid)
  full=document(uid,'2040-01-01','qa_calories',total_expenditure_kcal=2400,active_expenditure_kcal=600,resting_expenditure_kcal=1800,steps=1200)
  second,_=import_daily_energy_file(upload(full),uid)
  cases['partial_then_full_different_source_rows']=db.session.query(DailyEnergy).filter_by(user_id=uid,date=date(2040,1,1)).count()
  assert cases['partial_then_full_different_source_rows']==2
  for label,doc in [('renamed_replay',full),('additional_values',{**full,'data':{**full['data'],'distance_meters':800}})]:
   try:import_daily_energy_file(upload(doc),uid)
   except DailyEnergyImportError:cases[label]='rejected same date/source instead of merge'
   else:raise AssertionError(label)
  executor=StandardImportExecutor()
  null_doc={**full,'data':{**full['data'],'total_expenditure_kcal':None}}
  cases['public_null']=executor.plan_documents([null_doc],user_id=uid,target_type='daily_energy')['operations'][0]['operation']
  assert cases['public_null']=='invalid'
  executor._apply_daily_energy(null_doc,uid,second.id);db.session.flush()
  cases['internal_explicit_null_erases']=second.total_calories is None
  assert cases['internal_explicit_null_erases'];db.session.rollback()
  for when,day in [('before','2040-01-02'),('after','2040-01-03')]:
   if when=='after':import_daily_energy_file(upload(document(uid,day,'qa_calories',total_expenditure_kcal=2200)),uid)
   mobile_health.create_steps(uid,{'date':day,'steps':1300,'source':'health_connect_aggregate','client_event_id':str(uuid.uuid4())});db.session.commit()
   if when=='before':import_daily_energy_file(upload(document(uid,day,'qa_calories',total_expenditure_kcal=2200)),uid)
   cases['mobile_'+when+'_rows']=db.session.query(DailyEnergy).filter_by(user_id=uid,date=date.fromisoformat(day)).count()
  # A newer steps-only source hides known expenditure in one reader but not the trend reader.
  day=date(2040,1,3);rows=db.session.execute(db.select(DailyEnergy).where(DailyEnergy.user_id==uid,DailyEnergy.date==day).order_by(DailyEnergy.updated_at.desc(),DailyEnergy.id.desc())).scalars().all()
  cases['daily_vs_trend_disagree']=effective_energy_record(uid,day).total_calories is None and effective_energy_value(rows,'total_calories')[0]==2200
  assert cases['daily_vs_trend_disagree']
  client=app.test_client()
  with client.session_transaction() as session:session['_user_id']=str(uid);session['_fresh']=True
  cases['edit_route']=client.get(f'/daily-energy/{first.id}/edit').status_code
  cases['delete_route']=client.post(f'/daily-energy/{first.id}/delete').status_code
  assert cases['edit_route']==404 and cases['delete_route']==404
  # Concurrent independent sources both pass the database constraint for the same owner/day.
  db.session.rollback();barrier=threading.Barrier(2)
  def writer(source):
   with app.app_context():
    db.session.add(DailyEnergy(user_id=uid,date=date(2040,1,4),steps=100,source=source));barrier.wait();db.session.commit();return 'committed'
  with concurrent.futures.ThreadPoolExecutor(2) as pool:cases['concurrent_sources']=list(pool.map(writer,['qa_concurrent_a','qa_concurrent_b']))
  assert cases['concurrent_sources']==['committed','committed']
  cases['same_file_replay']=import_daily_energy_file(first.source_file,uid)[1]
  cases['same_values_other_source']='preserved as second daily row (not canonical)'
  report['isolations'][level]=cases
Path('/evidence/baseline-reproduction.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
