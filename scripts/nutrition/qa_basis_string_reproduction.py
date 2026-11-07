"""Reproduce the public prior code with invented data in temporary SQLite only."""
import ast
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
os.environ['FLASK_SKIP_DOTENV']='1'
from app import create_app
from app.extensions import db
from app.models import User,UploadedFile,NutritionImportDraft,MealLog,FoodProduct,NutritionImportReceipt
from app.services import nutrition_import as imports,nutrition_import_review as review,nutrition_math
from qa_pending_basis_fixtures import source18

BASE='4ed7d7620ea969ac0b4179bf7e40b8811b213a1d'

def old_function(path,name,module):
    source=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT).decode('utf-8')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace=dict(vars(module))
    exec(compile(ast.Module(body=[node],type_ignores=[]),path,'exec'),namespace)
    return namespace[name]


def run():
    document=source18();document['data']['entries']=document['data']['entries'][:14]
    for entry in document['data']['entries']:
        entry['declaration']['provenance']['basis_interpretation']='Los nutrientes corresponden a la porción consumida.'
    payload=json.dumps(document).encode();traces=[]
    class Capture(logging.Handler):
        def emit(self,record):
            if not record.exc_info:return
            traces.append({'exception':type(record.exc_info[1]).__name__,
                'message':str(record.exc_info[1]),'frames':[
                    {'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                    for f in traceback.extract_tb(record.exc_info[2]) if 'nutrition' in Path(f.filename).name]})
    with tempfile.TemporaryDirectory(prefix='qa40-fictional-') as directory:
        root=Path(directory)
        app=create_app(dict(TESTING=True,PROPAGATE_EXCEPTIONS=False,WTF_CSRF_ENABLED=False,
            SECRET_KEY='QA fictional key long enough for isolated reproduction',
            API_TOKEN_SIGNING_KEY='QA fictional API signing key for isolated reproduction',
            SQLALCHEMY_DATABASE_URI='sqlite://',SQLALCHEMY_ENGINE_OPTIONS={},DATA_ROOT=root,
            UPLOAD_ROOT=root/'uploads/raw',GENERATED_UPLOAD_ROOT=root/'generated',PORTABILITY_ROOT=root/'portability',
            SCHEMA_ROOT=ROOT/'schemas',NUTRITION_INTELLIGENCE_ENABLED=True,AI_ENABLED=False,
            NUTRITION_EXTERNAL_LOOKUP_ENABLED=False,ADMIN_USERNAME='QA admin',ADMIN_PASSWORD='fictional-only'))
        app.logger.handlers=[Capture()];app.logger.propagate=False
        with app.app_context():
            db.create_all();user=User(username='QA repro',role='user');user.set_password('fictional-only')
            db.session.add(user);db.session.commit();client=app.test_client()
            client.post('/login',data={'username':user.username,'password':'fictional-only'})
            current=imports._review_from_source
            imports._review_from_source=old_function('backend/app/services/nutrition_import.py','_review_from_source',imports)
            try:before=client.post('/nutrition/import',data={'file':(io.BytesIO(payload),'QA fictional 14.json')})
            finally:imports._review_from_source=current
            assert before.status_code==500 and traces[-1]['exception']=='AttributeError'
            assert db.session.query(UploadedFile).count()==db.session.query(NutritionImportDraft).count()==0
            assert not any(p.is_file() for p in root.rglob('*'))
            after=client.post('/nutrition/import',data={'file':(io.BytesIO(payload),'QA fictional 14.json')})
            assert after.status_code==302 and client.get(after.location).status_code==200
            row=db.session.scalar(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==user.id))
            view=review.overview(row);assert view['declared_basis_count']==14
            snapshot=imports.meal_snapshot(document['data']['entries'][0],[],'UTC')
            old_summary=old_function('backend/app/services/nutrition_math.py','snapshot_summary',nutrition_math)
            try:old_summary(snapshot)
            except AttributeError as error:secondary=type(error).__name__+': '+str(error)
            else:raise AssertionError('Prior snapshot reader did not reproduce')
            assert len(nutrition_math.snapshot_summary(snapshot))==30
            assert all(db.session.query(model).count()==0 for model in [MealLog,FoodProduct,NutritionImportReceipt])
            report={'status':'PASS','data':'entirely fictional','prior_sha':BASE,'before_HTTP':500,
                'before_tracebacks':traces,'prior_snapshot_reader':secondary,'after_upload_HTTP':302,
                'after_review_HTTP':200,'records':14,'proposed_group':14,'domain_writes':0,
                'prior_failed_import_orphan_files':0,'schema_changed':False}
            db.session.remove();db.drop_all()
    return report


if __name__=='__main__':
    result=run();target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
