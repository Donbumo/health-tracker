"""Local fictional UI QA only, ephemeral SQLite; never opens production storage."""
from pathlib import Path
import copy
import json
import sys
import tempfile
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,DailyNutrition,DailyEnergy,FoodProduct
from app.services import food_catalog as catalog,nutrition_intelligence as ni
from tests.test_nutrition_intelligence import food

root=Path(tempfile.mkdtemp(prefix='ht-nutrition-qa-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-nutrition-ui-qa-only-secret',
    'API_TOKEN_SIGNING_KEY':'fictional-nutrition-ui-qa-api-secret-only',
    'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS':{},'DATA_ROOT':root,'UPLOAD_ROOT':root/'raw',
    'GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portability',
    'SCHEMA_ROOT':Path(__file__).resolve().parents[2]/'schemas',
    'NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_QA_LABEL':True,'AI_ENABLED':False})
with app.app_context():
    db.create_all()
    user=User(username='nutrition-qa',role='user',display_name='QA ficticia',timezone='America/Mexico_City')
    user.set_password('fictional-nutrition-qa-password')
    db.session.add(user);db.session.commit()
    foods=[]
    for index,name in enumerate(['Pollo cocido QA ficticio','Arroz cocido QA ficticio','Aguacate QA ficticio','Salsa QA ficticia']):
        entry=copy.deepcopy(food());entry['name']=name;entry['source_food_id']='QA_'+str(index)
        entry['nutrients']['energy']['value']=str(100+index*30)
        entry['nutrients']['calcium']={'state':'known','value':str(10+index),'unit':'mg'}
        if index%2: entry['nutrients']['vitamin_d']={'state':'unknown','value':None,'unit':'ug'}
        foods.append(entry)
    catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'1','license':'QA synthetic','foods':foods})
    catalog.activate('qa_fictional','1',1);db.session.commit()
    refs=catalog.search(user.id)
    draft=ni.create_draft(user.id,name='Comida QA ficticia',target='2026-10-09',entries=[{'ref':ref['ref'],'amount':amount,'unit':'g'} for ref,amount in zip(refs,[60,200,180,30])])
    for i in range(4): draft=ni.mutate_draft(user.id,draft.public_id,draft.revision,'accept',{'index':i})
    ni.save_template(user.id,draft.public_id,draft.revision)
    log,_=ni.confirm(user.id,ni.confirmation_token(draft));db.session.commit()
    review=ni.repeat(user.id,log.public_id,'2026-10-09');db.session.commit()
    legacy=DailyNutrition(user_id=user.id,date=date(2026,10,8),source='qa',calories=1234,protein_g=50)
    db.session.add(legacy);db.session.commit()
    missing=FoodProduct(user_id=user.id,name='QA ficticio · energía desconocida',source='manual')
    db.session.add(missing);db.session.commit()
    partial=ni.create_draft(user.id,target='2026-10-07',name='QA subtotal parcial',entries=[
        {'ref':refs[0]['ref'],'amount':'100','unit':'g'},
        {'ref':'user:'+missing.public_id,'amount':'100','unit':'g'}])
    for i in range(2):partial=ni.mutate_draft(user.id,partial.public_id,partial.revision,'accept',{'index':i})
    ni.confirm(user.id,ni.confirmation_token(partial))
    db.session.add(DailyEnergy(user_id=user.id,date=date(2026,10,7),source='manual',total_calories=2000));db.session.commit()
    manifest={'draft':review.public_id,'food':refs[0]['ref'],'username':'nutrition-qa','port':8025}
    out=Path(__file__).resolve().parents[2]/'design/nutrition-intelligence-2/production-qa'
    out.mkdir(parents=True,exist_ok=True)
    (out/'qa-state.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Fictional QA only at http://127.0.0.1:8025',flush=True)
app.run(host='127.0.0.1',port=8025,debug=False,use_reloader=False)
