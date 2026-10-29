"""Loopback Flask QA, fictional daily structure and actual prior #30 parser."""
import copy,json,subprocess,sys,tempfile,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,MealLog,FoodProduct,NutritionImportReceipt
from app.services import food_catalog as catalog,nutrition_import as imports
from flask import render_template_string
from flask_login import current_user,login_required
root=Path(tempfile.mkdtemp(prefix='qa-legacy-semantic-ui-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-legacy-ui-long-secret-key-32-characters','API_TOKEN_SIGNING_KEY':'fictional-legacy-ui-api-long-key-32-characters',
 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},'SCHEMA_ROOT':ROOT/'schemas',
 'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads/raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable',
 'NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
modules={};sha='12bad71a60b96b57d282cfaf745fc0dc4ed27ab6'
for name,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py')]:
 code=subprocess.check_output(['git','show',sha+':'+path],cwd=ROOT);module=types.ModuleType('qa_'+name);exec(compile(code,sha+'/'+path,'exec'),module.__dict__);modules[name]=module
service=modules['service'];service.extract=modules['parser'].extract;service.EXTRACTOR_VERSION=modules['parser'].EXTRACTOR_VERSION
states={}
with app.app_context():
 db.create_all();fixture=ROOT/'examples/qa/nutrition-import-ux'
 catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text()));catalog.activate('qa_import_consumed','1',1);db.session.commit()
 for label in ['mobile','desktop','mobile-gate','desktop-gate']:
  owner=User(username='qa-semantic-'+label,role='user',display_name='QA ficticia',timezone='America/Mexico_City');owner.set_password('fictional-semantic-ui-password')
  db.session.add(owner);db.session.commit()
  ref=next(h['ref'] for h in catalog.search(owner.id,source='qa_import_consumed') if h['source_food_id']=='1')
  payload=json.loads((fixture/'legacy-daily-semantic-21.json').read_bytes())
  if label.endswith('gate'):payload['data']['meals'][0]['items'][1]['unit']='g'
  old=service.start(owner.id,json.dumps(payload).encode(),'QA daily legacy fictional.json')
  service.update(owner.id,old.public_id,old.revision,'destination',{'destination':'consumed','name':'QA revisión #30 conservada'})
  service.update(owner.id,old.public_id,old.revision,'bind',{'index':'0','ref':ref,'food_revision':'1','amount':'120','unit':'g'});db.session.commit()
  states[owner.id]={'key':old.public_id,'review':copy.deepcopy(old.review_json),'source':copy.deepcopy(old.source_json)}
@app.get('/qa/legacy')
@login_required
def qa_legacy():
 state=states[current_user.id];old=imports.owned(current_user.id,state['key'])
 logs=db.session.scalar(db.select(db.func.count(MealLog.id)).where(MealLog.user_id==current_user.id))
 products=db.session.scalar(db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id==current_user.id))
 receipts=db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==current_user.id))
 return render_template_string('<h1>QA ficticia · comprobación de integridad</h1><p>Logs: {{logs}} · Productos: {{products}} · Recibos: {{receipts}} · Revisión anterior intacta: {{intact}}</p><a href="/nutrition/import/{{key}}">Abrir revisión QA anterior</a>',logs=logs,products=products,receipts=receipts,intact=old.review_json==state['review'] and old.source_json==state['source'],key=state['key'])
print('Fictional legacy Flask QA ready on loopback 8038',flush=True)
app.run(host='127.0.0.1',port=8038,debug=False,use_reloader=False,load_dotenv=False)
