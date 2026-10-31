"""Reproduce the pre-fix HTTP 500 from public Git blobs and synthetic input."""
import io,json,sys,tempfile,subprocess,types,logging
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,UploadedFile
from qa_source_21_fixtures import source21

BASE='01b49cafc36ec95e11d0aed3aca11dcfdf49a5c0'
root=Path(tempfile.mkdtemp(prefix='issue36-fictional-baseline-'))
app=create_app(dict(TESTING=True,PROPAGATE_EXCEPTIONS=False,WTF_CSRF_ENABLED=False,
    SECRET_KEY='fictional-source21-baseline-secret-over-32-characters',
    API_TOKEN_SIGNING_KEY='fictional-source21-baseline-api-key-over-32-characters',
    SQLALCHEMY_DATABASE_URI='sqlite://',SQLALCHEMY_ENGINE_OPTIONS={},DATA_ROOT=root,
    UPLOAD_ROOT=root/'raw',GENERATED_UPLOAD_ROOT=root/'generated',PORTABILITY_ROOT=root/'portable',
    SCHEMA_ROOT=ROOT/'schemas',NUTRITION_INTELLIGENCE_ENABLED=True))
def legacy(name,path):
    module=types.ModuleType(name);module.__file__=path
    exec(compile(subprocess.check_output(['git','show',BASE+':'+path]),path,'exec'),module.__dict__)
    return module
parser=legacy('qa36_old_parser','backend/app/services/importers/nutrition_sources.py')
service=legacy('qa36_old_service','backend/app/services/nutrition_import.py');service.extract=parser.extract
failure=[]
def original_start(*args,**kwargs):
    kwargs.pop('commit',None)
    try:return service.start(*args,**kwargs)
    except Exception as error:failure.append(type(error).__name__);raise
with app.app_context():
    db.create_all();user=User(username='QA synthetic baseline',role='user');user.set_password('fictional-only')
    db.session.add(user);db.session.commit();client=app.test_client()
    client.post('/login',data=dict(username=user.username,password='fictional-only'))
    # Suppress the raw Flask exception: the evidence records class/frames only.
    app.logger.disabled=True
    with patch('app.services.nutrition_import.start',original_start):
        response=client.post('/nutrition/import',data={'file':(io.BytesIO(json.dumps(source21()).encode()),'QA synthetic baseline.json')})
    assert response.status_code==500 and failure==['JsonSchemaValidationError']
    db.session.rollback()
    report=dict(status='REPRODUCED',base=BASE,HTTP=response.status_code,exception=failure[0],
        frames=['nutrition_sources.json_rows: unconditional standard bypass','nutrition_import.start: stored original',
                'nutrition_import._review_from_source','validation.validate_json_document'],
        stored_uploads_after_failure=db.session.query(UploadedFile).count(),data='entirely fictional')
out=ROOT/'design/nutrition-source-21/qa';out.mkdir(parents=True,exist_ok=True)
(out/'baseline-500.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))
