"""Reproduce the old four-stage UI using fictional fixtures only.
Run against the base checkout with --app-root; never uses production storage/DB.
"""
import argparse,copy,io,json,re,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--app-root',type=Path,default=ROOT);args=parser.parse_args()
sys.path.insert(0,str(args.app_root/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,NutritionPlan
from app.services import food_catalog as catalog,nutrition_import as imports
root=Path(tempfile.mkdtemp(prefix='qa-nutrition-import-baseline-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-import-baseline-key-long-only','API_TOKEN_SIGNING_KEY':'fictional-baseline-signing-key-long','ADMIN_USERNAME':'qa-unused','ADMIN_PASSWORD':'fictional-only-password','SQLALCHEMY_DATABASE_URI':'sqlite://','SQLALCHEMY_ENGINE_OPTIONS':{},'SCHEMA_ROOT':args.app_root/'schemas','DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads'/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable','NUTRITION_INTELLIGENCE_ENABLED':True,'AI_ENABLED':False})
with app.app_context():
 db.create_all();owner=User(username='QA baseline only',role='user');owner.set_password('fictional-only');db.session.add(owner);db.session.commit()
 catalog.stage(json.loads((ROOT/'examples/qa/nutrition-import-ux/catalog.json').read_text()));catalog.activate('qa_import_ux','1',1);db.session.commit()
 hits=catalog.search(owner.id,source='qa_import_ux');refs={hit['source_food_id']:hit['ref'] for hit in hits}
 client=app.test_client();page=client.get('/login');csrf=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page.text)[1]
 assert client.post('/login',data={'username':owner.username,'password':'fictional-only','csrf_token':csrf}).status_code==302
 payload=(ROOT/'examples/qa/nutrition-import-ux/mixed-13.json').read_bytes()
 response=client.post('/nutrition/import',data={'csrf_token':csrf,'file':(io.BytesIO(payload),'QA mixed-13.json')});assert response.status_code==302
 key=response.location.rsplit('/',1)[1];row=imports.owned(owner.id,key);posts=1;mutations={};stage_gets=0
 def change(action,data):
  global posts
  response=client.post('/nutrition/import/'+key+'/change',data=dict(data,action=action,revision=row.revision,csrf_token=csrf));assert response.status_code==302,(action,response.status_code)
  posts+=1;mutations[action]=mutations.get(action,0)+1
 change('destination',{'destination':'plan','name':'QA mixed-13.json'})
 for step in [1,2,3,4]:
  response=client.get('/nutrition/import/'+key+'?step='+str(step));assert response.status_code==200 and ('PASO '+str(step)+' DE 4') in response.text;stage_gets+=1
  for index in range(13):
   item=row.review_json['rows'][index]
   if step==1:change('fields',dict(index=index,_section='identity',name=item['name'],date=item['date'],meal_type=item['meal_type']))
   if step==2:
    change('fields',dict(index=index,_section='composition',amount='200',unit='g',total_mass_g='200',composition_complete='yes'))
    for identity in ['1','2']:change('bind',dict(index=index,ref=refs[identity],food_revision='1',amount='100',unit='g'))
   if step==3:change('fields',dict(index=index,_section='declaration',basis_amount='200',basis_unit='g',nutrient_energy='200',nutrient_protein='10',**({'carbohydrate_classification':'unknown'} if index==12 else {})))
   if step==4:change('confirm',dict(index=index))
 page=client.get('/nutrition/import/'+key+'?step=4');token=re.search(r'name="token" value="([^"]+)"',page.text)[1]
 result=client.post('/nutrition/import/'+key+'/confirm',data={'revision':row.revision,'token':token,'csrf_token':csrf});posts+=1
 assert result.status_code==200 and db.session.query(NutritionPlan).count()==1
 report={'data':'fictional QA only','base':'430164e4f868e0ad5743b49223f87a330107c0b0','rows':13,'ingredients':26,'upload_POSTs':1,'mutation_POSTs':mutations,'domain_confirmation_POSTs':1,'total_POSTs':posts,'explicit_row_confirmations':13,'destination_confirmations':1,'stage_navigation_clicks':3,'minimum_submit_navigation_actions':posts+3,'blocking_rows_after_upload':13,'counting':'Submit-button activations plus three stage links; excludes file picker and field editing; upload/stage final GET reloads not counted as clicks','saved_meals':len(db.session.query(NutritionPlan).one().snapshot_json['meals'])}
 out=ROOT/'design/nutrition-import-ux/qa';out.mkdir(parents=True,exist_ok=True);(out/'baseline.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
