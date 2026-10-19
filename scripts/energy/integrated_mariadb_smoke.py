"""Run inside the ephemeral QA image, against loopback Gunicorn + LOCAL QA DB."""
import html
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import User
from app.services.energy_days import upsert_document, view
from app.services.validation import validate_json_document
from datetime import date

app = create_app()
username = 'QA-energy18-http-' + uuid.uuid4().hex
password = 'fictional-energy18-http-password'
with app.app_context():
    assert db.session.scalar(text('SELECT DATABASE()')) == 'nutrition_intelligence_qa_20261009'
    assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
    assert db.session.scalar(text('SELECT version_num FROM alembic_version')) == '20261018_0046'
    owner = User(username=username,role='user');owner.set_password(password)
    db.session.add(owner);db.session.commit();uid=owner.id
    for source,values in [('QA HTTP steps',{'steps':1200}),('QA HTTP energy',{'total_expenditure_kcal':2400,'active_expenditure_kcal':600})]:
        upsert_document({'schema_version':'1.0','record_type':'daily_energy','user_id':uid,'source_type':'uploaded',
            'data':{'date':'2040-04-01','source':source,**values}},uid)
    db.session.commit();record_id=view(uid,date(2040,4,1)).id

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
base='http://127.0.0.1:8000'
def get(path):
    return opener.open(base+path).read().decode()
def field(page,name):
    return html.unescape(re.search(r'name="'+name+r'"[^>]*value="([^"]*)"',page)[1])
def post(path, values):
    return opener.open(base+path,urllib.parse.urlencode(values).encode()).read().decode()

assert json.loads(get('/healthz'))['status']=='ok'
page=get('/login')
post('/login',{'username':username,'password':password,'csrf_token':field(page,'csrf_token')})
assert '2040-04-01' in get('/daily-energy')
edit=f'/daily-energy/{record_id}/edit'
page=get(edit)
payload={'date':'2040-04-01','steps':'1300','base_revision':field(page,'base_revision'),'csrf_token':field(page,'csrf_token')}
page=post(edit,payload)
assert '1300' in page and '2400' in page
try:
    post(edit,payload)
    raise AssertionError('stale edit accepted')
except urllib.error.HTTPError as error:
    assert error.code==409
export=json.loads(get(f'/daily-energy/{record_id}/export/json'))
with app.app_context():validate_json_document(export,'daily_energy')
assert export['schema_version']=='1.1' and export['data']['steps']==1300
assert len(export['evidence']['sources'])==2
delete=f'/daily-energy/{record_id}/delete'
page=get(delete)
post(delete,{'confirm':'y','base_revision':field(page,'base_revision'),'csrf_token':field(page,'csrf_token')})
assert '2040-04-01' not in get('/daily-energy')
report={'scope':'existing LOCAL MariaDB QA + real Gunicorn HTTP; fictional owner only','head':'20261018_0046',
    'healthz':'pass','login_csrf':'pass','canonical_day':'pass','partial_merge':'pass','edit_preserves_energy':'pass',
    'stale_revision_409':'pass','versioned_json_evidence':'pass','confirmed_delete':'pass','production_access':False}
Path('/evidence/integrated-http.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
