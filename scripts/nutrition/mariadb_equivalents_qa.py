"""B gate: existing LOCAL synthetic-only QA schema 0046; environment must be isolated.
No upgrade, stamp, schema reset, production fixture or dependency install.
Run in the approved runtime with /evidence pointing to QA output.
"""
import copy,json,re,uuid,tempfile
from pathlib import Path
from datetime import date
from flask_migrate import check
from sqlalchemy import event,text
from app import create_app
from app.extensions import db
from app.models import User,FoodProduct,MealDraft,MealLog
from app.services import nutrition_equivalents as eq,food_catalog as catalog
from app.services.nutrition_math import NutritionError
root=Path(tempfile.mkdtemp(prefix='qa-ni3-b-'))
app=create_app({'DATA_ROOT':root,'UPLOAD_ROOT':root/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False})
report={'status':'PASS','scope':'B working tree in A runtime; LOCAL synthetic-only MariaDB 0046','new_migrations':False}
with app.app_context():
 assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
 assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
 check(directory='/app/migrations')
 suffix=uuid.uuid4().hex[:10]
 owner=User(username='QA B '+suffix,role='user');owner.set_password('QA-fictional-B-password')
 other=User(username='QA B other '+suffix,role='user');other.set_password('QA-fictional-B-password')
 db.session.add_all([owner,other]);db.session.flush()
 original=FoodProduct(user_id=owner.id,name='QA B personal original '+suffix,source='manual',nutrition_json={'nutrients':{'vitamin_d':{'state':'known','value':'0','unit':'ug'}}})
 db.session.add(original);db.session.commit()
 before=(original.revision,copy.deepcopy(original.nutrition_json))
 source='qa_b_release_'+suffix
 food={'source':source,'source_food_id':'QA_PUBLISHED','revision':'1','name':'QA fictional published candidate '+suffix,'preparation':'QA cooked','basis_amount':'100','basis_unit':'g','servings':[],'nutrients':{'energy':{'state':'known','value':'100','unit':'kcal'},'iron':{'state':'known','value':'2','unit':'mg'},'vitamin_d':{'state':'known','value':'0','unit':'ug'}}}
 catalog.stage({'schema_version':'2.0','source':source,'revision':'1','license':'QA fictional only','foods':[food]});catalog.activate(source,'1',1);db.session.commit()
 hit=catalog.search(owner.id,source=source)[0]
 comparison=eq.comparison(owner.id,original.public_id,hit['ref'],'150','g',date(2042,1,1))
 statements=[]
 def guard(conn,cursor,stmt,params,context,many):
  op=stmt.lstrip().split()[0].upper();statements.append(op);assert op not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
 event.listen(db.engine,'before_cursor_execute',guard)
 client=app.test_client()
 try:
  login=client.get('/login');token=re.search(r'name="csrf_token"[^>]*value="([^"]*)"',login.text)[1]
  assert client.post('/login',data={'username':owner.username,'password':'QA-fictional-B-password','csrf_token':token}).status_code==302
  response=client.get('/nutrition/my-food/'+original.public_id+'/equivalents?q=chicken&candidate='+hit['ref']+'&amount=150&unit=g')
  assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
  assert original.nutrition_json==before[1] and '0 ug' in response.text
 finally:event.remove(db.engine,'before_cursor_execute',guard)
 try:eq.reviewed_selection(other.id,original.public_id,comparison['token'])
 except NutritionError as error:assert error.status==404
 else:raise AssertionError('Owner isolation failed')
 # Keep the CSRF token from the authenticated session; login now redirects.
 response=client.post('/nutrition/my-food/'+original.public_id+'/equivalents/prepare',data={'token':comparison['token'],'confirm_identity':'yes','csrf_token':token})
 assert response.status_code==302
 draft=db.session.scalar(db.select(MealDraft).where(MealDraft.user_id==owner.id))
 assert draft and draft.state=='pending' and draft.accepted_json==[]
 assert not db.session.scalar(db.select(db.func.count(MealLog.id)).where(MealLog.user_id==owner.id))
 assert (original.revision,original.nutrition_json)==before
 report.update(db_check='PASS',authenticated_GET='PASS',GET_DML=0,GET_DDL=0,owner_only='PASS',original_definition_unchanged=True,only_pending_official_draft=True,consumption_writes=0)
Path('/evidence/mariadb.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
