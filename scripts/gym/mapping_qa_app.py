"""Local fictional UI QA; never loads production data or downloads media."""
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services.exercise_catalog import sync_catalog
from app.services.gym_programs import confirm_program, preview_token, resolve_draft
from app.services.gym_sessions import start_session
from app.services.importers.routine_draft import DeterministicParser
from tests.test_external_exercise_catalog import FixtureSource, sample

root=Path(os.environ['MAPPING_QA_ROOT']).resolve()
assert root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and root.name.startswith('ht-mapping-qa-')
app=create_app({'SECRET_KEY':'fictional-mapping-qa-secret-only-long', 'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.db').as_posix(),
    'DATA_ROOT':root,'PORTABILITY_ROOT':root/'portability','UPLOAD_ROOT':root/'uploads','GENERATED_UPLOAD_ROOT':root/'generated','EXERCISE_CATALOG_ROOT':root/'catalog',
    'SCHEMA_ROOT':Path(__file__).resolve().parents[2]/'schemas','ADMIN_USERNAME':'qa-unused','ADMIN_PASSWORD':'fictional-qa-only'})
with app.app_context():
    db.create_all()
    user=db.session.execute(db.select(User).where(User.username=='mapping-qa')).scalar_one_or_none()
    if user is None:
        user=User(username='mapping-qa',display_name='QA demo ficticia',role='user');user.set_password('fictional-qa-password')
        db.session.add(user);db.session.commit()
        sync_catalog(source=FixtureSource(entries=[sample('QA_A','QA Leg Press'),sample('QA_B','QA Narrow Stance Leg Press'),sample('QA_C','QA Smith Machine Leg Press'),sample('QA_D','QA Seated Leg Curl')]))
        csv=b'Day,Exercise,Sets,Reps\nQA Day,QA prensa,2,8\nQA Day,QA curl femoral sentado,2,8\nQA Day,QA unknown exercise,2,8'
        draft=DeterministicParser().parse(csv,'qa.csv','QA routine - fictional')
        for ex in draft.days[0]['exercises']:ex['create_new']=True
        resolve_draft(draft,user.id)
        plan,_=confirm_program(draft,user.id,preview_token(draft,user.id));db.session.commit()
        start_session(user.id,plan.public_id,plan.versions[0].public_id,1,1,'00000000-0000-4000-8000-000000000014');db.session.commit()
    db.session.remove();db.engine.dispose()
# Runtime HTTP must be local. SQL uses the isolated SQLite file.
import urllib.request

def offline(*args,**kwargs):
    raise RuntimeError('Outbound HTTP disabled for mapping QA')
urllib.request.OpenerDirector.open=offline
# QA-only stylesheet override makes both existing palettes inspectable without
# changing system/browser preferences or production CSS.
from flask import request, Response
import re

@app.get('/qa/theme.css')
def qa_theme_css():
    css=(Path(app.static_folder)/'css/app.css').read_text(encoding='utf-8')
    media='all' if request.args.get('theme')=='dark' else 'not all'
    return Response(css.replace('(prefers-color-scheme: dark)',media),mimetype='text/css')

@app.after_request
def qa_theme(response):
    theme=request.args.get('qa_theme')
    if theme in {'light','dark'} and response.mimetype=='text/html':
        html=response.get_data(as_text=True)
        html=re.sub(r'href="/static/css/app.css[^\"]*"', 'href="/qa/theme.css?theme='+theme+'"', html)
        response.set_data(html)
    return response

if __name__=='__main__':app.run(host='127.0.0.1',port=8014,use_reloader=False,load_dotenv=False)
