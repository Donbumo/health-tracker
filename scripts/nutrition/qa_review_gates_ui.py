"""Loopback temporary QA: actual #29 active/expired drafts, no production."""
import copy,json,sys,tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,MealLog,FoodProduct,NutritionImportReceipt,NutritionImportDraft
from app.services import food_catalog as catalog,nutrition_import as imports
from qa_legacy_import_29 import legacy_review
root=Path(tempfile.mkdtemp(prefix='qa-review-gates-ui-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-review-gates-ui-32-characters','API_TOKEN_SIGNING_KEY':'fictional-review-gates-api-32-characters',
 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},'SCHEMA_ROOT':ROOT/'schemas',
 'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads/raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable',
 'NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
states={}
with app.app_context():
 db.create_all();fixture=ROOT/'examples/qa/nutrition-import-ux'
 catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text(encoding='utf-8')));catalog.activate('qa_import_consumed','1',1);db.session.commit()
 for label,expired in [('mobile',False),('desktop',True)]:
  owner=User(username='qa-gates-'+label,role='user',display_name='QA ficticia',timezone='America/Mexico_City')
  owner.set_password('fictional-review-gates-password');db.session.add(owner);db.session.commit()
  ref=next(h['ref'] for h in catalog.search(owner.id,source='qa_import_consumed') if h['source_food_id']=='1')
  old=legacy_review(owner.id,(fixture/'consumed-text-portions-21.json').read_bytes(),ref)
  if expired:old.created_at-=timedelta(days=2);db.session.commit()
  states[owner.id]={'key':old.public_id,'review':copy.deepcopy(old.review_json),'source':copy.deepcopy(old.source_json),'created':old.created_at,'expired':expired}
 owner=User(username='qa-gates-context',role='user',display_name='QA ficticia',timezone='America/Mexico_City')
 owner.set_password('fictional-review-gates-password');db.session.add(owner);db.session.commit()
 raw={'destination':'consumed','records':[{'name':'QA pieza variable','amount':'1 pieza de peso variable','basis_amount':'100','basis_unit':'g','kcal':'100','protein_g':'5','date':'2026-10-26','meal_type':'lunch'}]}
 row=imports.start(owner.id,json.dumps(raw).encode(),'QA pieza variable.json');db.session.commit()
 states[owner.id]={'key':row.public_id,'review':copy.deepcopy(row.review_json),'source':copy.deepcopy(row.source_json),'created':row.created_at,'expired':False,'contextual':True}
from flask import jsonify
from flask_login import current_user,login_required
@app.get('/qa/state')
@login_required
def qa_state():
 state=states[current_user.id];return jsonify(key=state['key'],expired=state['expired'])
@app.get('/qa/result')
@login_required
def qa_result():
 state=states[current_user.id];old=imports.owned(current_user.id,state['key'])
 logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==current_user.id)).all()
 return jsonify(logs=len(logs),products=db.session.scalar(db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id==current_user.id)),
  receipts=db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==current_user.id)),
  previous_unchanged=old.review_json==state['review'] and old.source_json==state['source'] and old.created_at==state['created'] and old.revision==5,
  total_kcal=str(sum((Decimal(log.snapshot_json['summary']['energy']['value']) for log in logs),Decimal(0))),
  corrected_name_kept=any(log.snapshot_json['name']=='QA nombre corregido por usuario' for log in logs))
print('Synthetic review gates UI ready on loopback 8037',flush=True)
app.run(host='127.0.0.1',port=8037,debug=False,use_reloader=False,load_dotenv=False)
