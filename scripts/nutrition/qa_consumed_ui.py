"""Fictional loopback-only, disposable SQLite reproduction of 21 consumed rows."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services import food_catalog as catalog,nutrition_import as imports
root=Path(tempfile.mkdtemp(prefix='qa-consumed-21-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-consumed-ui-key-only-32-characters','API_TOKEN_SIGNING_KEY':'fictional-consumed-ui-api-key-32-characters','SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},'SCHEMA_ROOT':ROOT/'schemas','DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads'/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
with app.app_context():
 db.create_all();fixture=ROOT/'examples/qa/nutrition-import-ux'
 catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text(encoding='utf-8')));catalog.activate('qa_import_consumed','1',1);db.session.commit()
 for name in ['qa-consumed-mobile','qa-consumed-desktop']:
  owner=User(username=name,role='user',display_name='QA ficticia',timezone='America/Mexico_City');owner.set_password('fictional-consumed-password');db.session.add(owner)
 db.session.commit()
from flask import jsonify
from flask_login import current_user,login_required
@app.get('/qa/result')
@login_required
def qa_result():
 from app.models import MealLog,FoodProduct,NutritionImportReceipt
 logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==current_user.id)).all()
 return jsonify(logs=len(logs),products=db.session.scalar(db.select(db.func.count(FoodProduct.id)).where(FoodProduct.user_id==current_user.id)),
  receipts=db.session.scalar(db.select(db.func.count(NutritionImportReceipt.id)).where(NutritionImportReceipt.user_id==current_user.id)),
  bound_snapshots=sum(bool(log.snapshot_json['ingredients']) for log in logs),
  candidate_bound=any(log.snapshot_json['name']=='QA pechuga de pollo asada' and log.snapshot_json['ingredients'] for log in logs))
print('Synthetic 21-row UI QA ready on loopback 8036',flush=True)
app.run(host='127.0.0.1',port=8036,debug=False,use_reloader=False,load_dotenv=False)
