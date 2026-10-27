"""Loopback-only Flask QA, temporary SQLite and fictional food catalog."""
import argparse,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--app-root',type=Path,default=ROOT);parser.add_argument('--port',type=int,default=8035);parser.add_argument('--baseline',action='store_true');parser.add_argument('--closeout',action='store_true');args=parser.parse_args()
sys.path.insert(0,str(args.app_root/'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services import food_catalog as catalog,nutrition_import as imports
root=Path(tempfile.mkdtemp(prefix='qa-nutrition-import-ui-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-nutrition-import-ui-key-only','API_TOKEN_SIGNING_KEY':'fictional-nutrition-import-api-key-only','ADMIN_USERNAME':'qa-unused','ADMIN_PASSWORD':'fictional-qa-password','SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},'SCHEMA_ROOT':args.app_root/'schemas','DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads'/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
with app.app_context():
 db.create_all();owner=User(username='import-ux-qa',role='user',display_name='QA ficticia',timezone='America/Mexico_City');owner.set_password('fictional-import-ux-password');db.session.add(owner);db.session.commit()
 fixture=ROOT/'examples/qa/nutrition-import-ux';catalog.stage(json.loads((fixture/'catalog.json').read_text(encoding='utf-8')));catalog.activate('qa_import_ux','1',1);db.session.commit()
 row=imports.start(owner.id,(fixture/'mixed-13.json').read_bytes(),'QA mixed-13.json');db.session.commit()
 out=ROOT/'design/nutrition-import-ux/qa';out.mkdir(parents=True,exist_ok=True)
 if args.closeout:
  from datetime import timedelta
  imports.update(owner.id,row.public_id,row.revision,'fields',{'index':0,'_section':'identity','name':'QA expired review','meal_type':'lunch'})
  row.created_at-=timedelta(days=2);db.session.commit()
  catalog.stage(json.loads((fixture/'representative-catalog.json').read_text(encoding='utf-8')));catalog.activate('qa_diet_closeout','1',1);db.session.commit()
  representative=imports.start(owner.id,(fixture/'representative-plan.csv').read_bytes(),'QA plan sin IDs.csv');db.session.commit()
  (out/'closeout-state.json').write_text(json.dumps({'expired':row.public_id,'representative':representative.public_id,'data':'fictional QA only'})+'\n',encoding='utf-8')
 (out/('baseline-state.json' if args.baseline else 'ui-state.json')).write_text(json.dumps({'key':row.public_id,'data':'fictional QA only'})+'\n',encoding='utf-8')
print('Synthetic UI QA ready on loopback '+str(args.port),flush=True)
app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False,load_dotenv=False)
