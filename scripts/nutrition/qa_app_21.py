"""Real Flask/Jinja Nutrition 2.1 QA with an ephemeral, fictional account.

Reuses localhost:8025. Never opens the personal local DB or production storage.
Public food catalog is real; every account/meal/plan is labelled QA fictional.
"""
import copy
import json
import sys
import tempfile
import time
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,DailyNutrition,DailyEnergy,FoodProduct,NutritionMeal,NutritionItem,Recipe
from app.services import food_catalog as catalog,nutrition_intelligence as ni,nutrition_import as imports
from app.services.importers.standard_import_executor import StandardImportExecutor
from app.models.nutrition_intelligence import CatalogFood,FoodCatalogRevision

out=ROOT/'design/nutrition-intelligence-2-1/qa';out.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='ht-nutrition21-qa-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-nutrition21-ui-qa-secret-only',
 'API_TOKEN_SIGNING_KEY':'fictional-nutrition21-ui-qa-api-key-only','SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),
 'SQLALCHEMY_ENGINE_OPTIONS':{},'DATA_ROOT':root,'UPLOAD_ROOT':root/'uploads/raw','GENERATED_UPLOAD_ROOT':root/'uploads/generated',
 'PORTABILITY_ROOT':root/'portable','SCHEMA_ROOT':ROOT/'schemas','NUTRITION_INTELLIGENCE_ENABLED':True,
 'NUTRITION_EXTERNAL_LOOKUP_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False})
# Explicitly synthetic upstream fixture for end-to-end UI; no external request.
from app.services.nutrition_sources import public_lookup,off_food
from app.services.nutrition_math import NutritionError
def fictional_off_lookup(query,*,consent=False):
 if not consent:raise NutritionError('Confirma la consulta pública.')
 if query!='0000000000001':return []
 return [off_food({'code':'0000000000001','product_name':'QA OFF bebida ficticia','brands':'QA comercial',
    'nutrition_data_per':'100ml','quantity':'500 ml','last_modified_t':123,
    'nutriments':{'energy-kcal_100g':45,'proteins_100g':0,'carbohydrates_100g':7,'sodium_100g':.03}})]
public_lookup.lookup=fictional_off_lookup
with app.app_context():
 db.create_all()
 user=User(username='nutrition-qa',role='user',display_name='QA ficticia',timezone='America/Mexico_City');user.set_password('fictional-nutrition-qa-password')
 db.session.add(user);db.session.commit()
 counts=[]
 for p in sorted((ROOT/'examples/catalog/nutrition-2-1').glob('*.json')):
  if p.name=='manifest.json':continue
  doc=json.loads(p.read_bytes());t=time.perf_counter();catalog.stage(doc);catalog.activate(doc['source'],doc['revision'],1);db.session.commit()
  counts.append({'source':doc['source'],'foods':len(doc['foods']),'seconds':round(time.perf_counter()-t,3)})
  print(json.dumps(counts[-1]),flush=True)
 def public_ref(identity):
  food=db.session.execute(catalog.catalog_query().where(CatalogFood.source_food_id==identity,FoodCatalogRevision.source_id=='usda_sr_legacy')).scalar_one()
  return 'catalog:'+food.public_id
 ref=public_ref('171477');rice_ref=public_ref('169757')
 missing=FoodProduct(user_id=user.id,name='QA ficticio · ingrediente sin datos',source='manual');db.session.add(missing);db.session.commit()
 for i in range(30):
  target=date(2026,9,13)+timedelta(days=i)
  if i in (4,17,26):
   if i%4:db.session.add(DailyEnergy(user_id=user.id,date=target,source='qa',total_calories=2100+i));db.session.commit()
   continue
  if i%3==0:
   day=DailyNutrition(user_id=user.id,date=target,source='qa',calories=1200+i*10,protein_g=40,total_carbs_g=70,fat_g=25)
   if i==12:day.calories=0;day.protein_g=0;day.total_carbs_g=0;day.fat_g=0
   db.session.add(day);db.session.flush()
   if i!=12:
    meal=NutritionMeal(user_id=user.id,daily_nutrition_id=day.id,meal_type='lunch',name='Comida legacy QA ficticia',sort_order=1)
    db.session.add(meal);db.session.flush();db.session.add(NutritionItem(user_id=user.id,nutrition_meal_id=meal.id,name='Arroz y pollo legacy QA ficticio',sort_order=1,source='qa',calories=500,protein_g=25))
  else:
   entries=[{'ref':ref,'amount':'150','unit':'g'}]
   if i%5==0:entries.append({'ref':'user:'+missing.public_id,'amount':'25','unit':'g'})
   draft=ni.create_draft(user.id,target=target.isoformat(),name='Comida QA ficticia',entries=entries)
   for index in range(len(entries)):ni.mutate_draft(user.id,draft.public_id,draft.revision,'accept',{'index':index})
   ni.confirm(user.id,ni.confirmation_token(draft))
  if i%4:db.session.add(DailyEnergy(user_id=user.id,date=target,source='qa',total_calories=2100+i))
  db.session.commit()
 fixture=ROOT/'examples/nutrition-2-1/fixtures/compound-macros.json'
 review=imports.start(user.id,fixture.read_bytes(),fixture.name)
 doc=copy.deepcopy(review.review_json);doc.update(destination='plan',name='Plan prescrito QA ficticio')
 doc['rows'][0].update(confirmed=True,ingredients=[{'ref':chosen,'food_revision':catalog.detail(user.id,chosen)['revision'],'amount':amount,'unit':'g'} for chosen,amount in [(ref,'80'),(rice_ref,'140')]])
 review.review_json=doc;db.session.commit()
 result=StandardImportExecutor().commit_documents([imports.canonical(review)],user_id=user.id,target_type='nutrition_import',confirmed=True)
 assert result['committed'],result
 from app.models import NutritionPlan
 plan=db.session.query(NutritionPlan).one()
 draft=imports.use_plan(user.id,plan.public_id,0,'2026-10-12');db.session.commit()
 photo=ROOT/'examples/nutrition-2-1/fixtures/label.png';photo_review=imports.start(user.id,photo.read_bytes(),photo.name);db.session.commit()
 private=ROOT/'examples/nutrition-2-1/fixtures/external.json'
 retention=imports.start(user.id,private.read_bytes(),'QA original privado para cancelar.json');db.session.commit()
 imports.update(user.id,retention.public_id,retention.revision,'cancel',{});db.session.commit()
 for index in range(125):
  db.session.add(FoodProduct(user_id=user.id,name=f'QA biblioteca producto {index:03}',brand='QA ficticia',source='manual'))
  db.session.add(Recipe(user_id=user.id,name=f'QA biblioteca receta {index:03}',servings=1))
 db.session.commit()
 from app.services.nutrition_history import history
 view=history(user.id,date(2026,10,12),30)
 week=history(user.id,date(2026,10,12),7);month_by_date={p['date']:p for p in view['points']}
 assert all(p['rolling_energy']==month_by_date[p['date']]['rolling_energy'] for p in week['points'])
 (out/'chart-report.json').write_text(json.dumps({'data':'QA synthetic only','period_consistency':'7 vs 30 day moving windows pass','points':[
  {'date':p['date'].isoformat(),'intake':str(p['values']['calories']) if p['values']['calories'] is not None else None,
   'state':p['states']['calories'],'expended':str(p['expended']) if p['expended'] is not None else None,
   'balance':str(p['balance']) if p['balance'] is not None else None,
   'rolling':{k:str(v) if v is not None else None for k,v in p['rolling_energy'].items()},
   'rolling_days':p['rolling_energy_days'],'legacy':p['legacy']} for p in view['points']]},indent=2)+'\n',encoding='utf-8')
 searches=['arroz','arroz blanco cocido','arroz integral','rice raw','rice cooked','pollo','pechuga pollo cocida','chicken raw','chicken roasted',
 'frijol','frijoles negros','frijoles pintos','tortilla','tortilla maiz','tortilla harina','avena','oats raw','leche','yogur','queso','huevo','aguacate','atun',
 'salmon','papa','platano','lentejas','garbanzos','cebolla','espinaca','cacahuate','cerdo','nopal','zanahoria','calabaza','calabacita','chile','pepino',
 'naranja','fresas','piña','mango','pavo','brocoli','papaya','guayaba','quinoa','camaron','coca','bimbo','nestle','Premier Protein','QA ficticio', 'THIS_FOOD_DOES_NOT_EXIST_QA']
 searches.append(db.session.execute(catalog.catalog_query().where(FoodCatalogRevision.source_id=='open_food_facts')).scalars().first().barcode)
 report=[]
 for query in searches:
  t=time.perf_counter();results=catalog.search(user.id,query);elapsed=(time.perf_counter()-t)*1000
  report.append({'query':query,'results':len(results),'ms':round(elapsed,3),'first':[r['name'] for r in results[:3]],
    'review':'candidate identities only; no automatic equivalence' if results else 'not present in bounded local sample; explicit external lookup/manual review available'})
 manifest={'username':'nutrition-qa','port':8025,'food':ref,'rice':rice_ref,'draft':draft.public_id,'import':review.public_id,'label':photo_review.public_id,'retention':retention.public_id,
    'catalog':counts,'history_days':30,'data':'QA synthetic only'}
 (out/'qa-state.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (out/'search-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 rank_cases=[('tortilla de maíz','175036'),('tortilla de maiz','175036'),('tortilla maíz','175036'),
  ('totopos',None),('arroz blanco cocido','169757'),('white rice cooked',None),('pollo crudo',None),
  ('pollo cocido','171477'),('frijoles','173735'),('frijoles negros','173735'),('frijoles pintos','175200'),
  ('avena','169705'),('avena seca','169705'),('coca',None),('bimbo',None),('nestle',None),
  ('THIS_FOOD_DOES_NOT_EXIST_QA',None)]
 rank=[]
 for query,expected in rank_cases:
  times=[]
  for trial in range(5):
   t=time.perf_counter();matches=catalog.search(user.id,query);times.append(round((time.perf_counter()-t)*1000,3))
  top=[{k:hit[k] for k in ('name','preparation','source','source_food_id','state','brand')} for hit in matches[:5]]
  rank.append({'query':query,'expected_sr_identity':expected,'expected_rank':next((i+1 for i,h in enumerate(matches)
   if h['source']=='usda_sr_legacy' and h['source_food_id']==expected),None) if expected else None,
   'timings_ms':times,'top_5':top,'candidates':len(matches)})
 (out/'ranking-report.json').write_text(json.dumps({'data':'public catalog; synthetic owner','repeat_each_query':5,
  'ranking_contract':'Lexical candidates only; no merge or automatic identity selection','cases':rank},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('QA fictional Flask ready at http://127.0.0.1:8025',flush=True)
app.run(host='127.0.0.1',port=8025,debug=False,use_reloader=False)
