import copy,json,uuid,hashlib,concurrent.futures,threading
from pathlib import Path
from datetime import date
from sqlalchemy import text,inspect
from flask_migrate import upgrade,check
from app import create_app
from app.extensions import db
from app.models import User,DailyEnergy,EnergyDay
from app.services import energy_days as e,mobile_health
SCHEMA='nutrition_intelligence_qa_20261009';HEAD='20261018_0046'
report={'scope':'LOCAL isolated QA; synthetic fixtures only','migration':{},'isolations':{}}
app=create_app({'DATA_ROOT':Path('/tmp/energy18-maria'),'TESTING':True,'NUTRITION_INTELLIGENCE_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
def owner():
 row=User(username='QA-energy18-final-'+uuid.uuid4().hex,role='user');row.set_password('fictional-QA-only');db.session.add(row);db.session.commit();return row.id
def doc(uid,source='qa_a',day='2040-03-01',**values):
 return {'schema_version':'1.0','record_type':'daily_energy','user_id':uid,'source_type':'uploaded','data':{'date':day,'source':source,**values}}
def fingerprint(table,columns=None):
 cols=columns or [row['name'] for row in inspect(db.engine).get_columns(table)]
 # Identifiers come only from inspected local metadata, never an uploaded payload.
 result=db.session.execute(text('SELECT '+','.join('`'+c+'`' for c in cols)+' FROM `'+table+'` ORDER BY id')).all()
 return hashlib.sha256(repr(result).encode()).hexdigest()
with app.app_context():
 assert db.session.scalar(text('SELECT DATABASE()'))==SCHEMA
 assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
 current=db.session.scalar(text('SELECT version_num FROM alembic_version'))
 report['mariadb']=db.session.scalar(text('SELECT VERSION()'))
 if current=='20261013_0045':
  uid=owner()
  for source,steps,total in [('qa_partial',1200,None),('qa_full',1200,2400),('qa_conflict',None,2500)]:
   db.session.execute(text('INSERT INTO daily_energy (public_id,user_id,date,source,steps,total_calories,revision) VALUES (:pid,:uid,:day,:source,:steps,:total,1)'),{'pid':str(uuid.uuid4()),'uid':uid,'day':'2040-03-01','source':source,'steps':steps,'total':total})
  db.session.commit()
  columns=[row['name'] for row in inspect(db.engine).get_columns('daily_energy')]
  before=fingerprint('daily_energy',columns)
  guarded=['daily_nutrition','nutrition_meals','nutrition_items','meal_logs','catalog_foods','recipes']
  hashes={table:fingerprint(table) for table in guarded}
  db.session.rollback()
  upgrade(directory='/app/migrations')
  assert db.session.scalar(text('SELECT version_num FROM alembic_version'))==HEAD
  assert fingerprint('daily_energy',columns)==before
  assert all(fingerprint(table)==digest for table,digest in hashes.items())
  assert e.view(uid,date(2040,3,1)).total_calories is None
  assert e.view(uid,date(2040,3,1)).steps==1200
  report['migration']={'from':current,'to':HEAD,'original_energy_columns_hash':'identical','nutrition_recipes_snapshots_catalog_hashes':'identical','legacy_synthetic_duplicates':'one canonical day; three untouched source UUIDs; conflict unknown'}
 else:
  assert current==HEAD
  report['migration']={'current':HEAD,'repeat':'already at head'}
 check(directory='/app/migrations')
 db.session.rollback();upgrade(directory='/app/migrations')
 assert 'uq_energy_day_user_date' in {row['name'] for row in inspect(db.engine).get_unique_constraints('energy_days')}
 assert db.session.scalar(text('SELECT COUNT(*) FROM (SELECT user_id,date FROM energy_days GROUP BY user_id,date HAVING COUNT(*)>1) AS duplicates'))==0
 report['migration']['db_check']='pass';report['migration']['repeated_upgrade']='safe no-op'
 Path('/evidence/mariadb-migration.json').write_text(json.dumps(report['migration'],indent=2))
for level in ['READ COMMITTED','REPEATABLE READ']:
 app=create_app({'DATA_ROOT':Path('/tmp/energy18-maria'),'TESTING':True,'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':level,'pool_pre_ping':True}})
 with app.app_context():
  assert db.session.scalar(text('SELECT DATABASE()'))==SCHEMA
  assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-',' ')==level
  uid=owner();other=owner();barrier=threading.Barrier(2)
  def writer(source):
   with app.app_context():
    barrier.wait();r=e.upsert_document(doc(uid,source,steps=1200,total_expenditure_kcal=2400),uid);db.session.commit();return r.public_id
  with concurrent.futures.ThreadPoolExecutor(2) as pool:ids=list(pool.map(writer,['qa_a','qa_b']))
  db.session.rollback()
  assert len(set(ids))==2
  result=e.view(uid,date(2040,3,1));assert result.total_calories==2400 and result.steps==1200
  assert db.session.query(EnergyDay).filter_by(user_id=uid).count()==1
  source=db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.user_id==uid,DailyEnergy.source=='qa_a'))
  revision=source.revision
  e.upsert_document(doc(uid,steps=1200,total_expenditure_kcal=2400),uid);db.session.commit();assert source.revision==revision
  e.upsert_document(doc(uid,total_expenditure_kcal=None,active_expenditure_kcal=0),uid);db.session.commit()
  assert source.total_calories==2400 and source.active_calories==0
  e.upsert_document(doc(uid,total_expenditure_kcal=2500),uid);db.session.commit()
  assert e.view(uid,date(2040,3,1)).total_calories is None
  rev=e.view(uid,date(2040,3,1)).revision
  db.session.rollback();barrier=threading.Barrier(2)
  def edit(value):
   with app.app_context():
    barrier.wait()
    try:e.edit_day(uid,date(2040,3,1),rev,{'total_calories':value});db.session.commit();return 'success'
    except e.EnergyConflict:db.session.rollback();return 'stale'
  with concurrent.futures.ThreadPoolExecutor(2) as pool:outcomes=list(pool.map(edit,[2450,2460]))
  assert sorted(outcomes)==['stale','success'],outcomes
  db.session.expire_all()
  assert e.view(other,date(2040,3,1)) is None
  # A failed transaction includes both evidence and its registry/event writes.
  rollback_day='2040-03-02'
  e.upsert_document(doc(uid,day=rollback_day,steps=1),uid);db.session.rollback()
  assert e.view(uid,date.fromisoformat(rollback_day)) is None
  event=str(uuid.uuid4());step=mobile_health.create_steps(uid,{'date':'2040-03-03','steps':1300,'source':'health_connect_aggregate','client_event_id':event});db.session.commit()
  pid=step.public_id
  e.upsert_document(doc(uid,source='health_connect_aggregate',day='2040-03-03',total_expenditure_kcal=2200),uid);db.session.commit()
  mobile_health.patch_steps(uid,pid,{'base_revision':step.revision,'steps':1400});db.session.commit()
  mobile_health.delete_steps(uid,pid,{'base_revision':step.revision});db.session.commit()
  assert e.view(uid,date(2040,3,3)).total_calories==2200 and step.public_id==pid
  recreated_payload={'date':'2040-03-03','steps':1500,'source':'health_connect_aggregate','client_event_id':str(uuid.uuid4())}
  recreated=mobile_health.create_steps(uid,recreated_payload);db.session.commit();recreated_revision=recreated.revision
  replay=mobile_health.create_steps(uid,recreated_payload);db.session.commit()
  assert replay.public_id==pid and replay.revision==recreated_revision
  assert e.view(uid,date(2040,3,3)).total_calories==2200
  report['isolations'][level]={'concurrent_sources':'2 identities, 1 canonical day','concurrent_review':outcomes,'same_event_revision':'unchanged','null_zero':'preserved','source_conflict':'unknown with evidence','ownership':'pass','rollback':'registry/evidence/events atomic','mobile':'stable UUID; create/patch/delete/recreate/replay retains expenditure'}
Path('/evidence/mariadb-final.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
