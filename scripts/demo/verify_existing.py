"""Owner-only verification over the deployed app and its real HTTP login."""
import json
import os

VERIFY = r'''
import http.client,json,sys
from datetime import date
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlencode
from app import create_app
from app.extensions import db
from app.models import User,DailyNutrition,TrainingSession
from app.services.daily_balance import daily_balance
password=json.load(sys.stdin)['password']
class Inputs(HTMLParser):
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('name')=='csrf_token':self.token=attrs['value']
cookies=SimpleCookie()
def request(method,path,body=None):
    connection=http.client.HTTPConnection('127.0.0.1',8000,timeout=30)
    headers={'Cookie':'; '.join(k+'='+v.value for k,v in cookies.items())}
    if body is not None:headers['Content-Type']='application/x-www-form-urlencoded'
    connection.request(method,path,body,headers)
    response=connection.getresponse()
    for name,value in response.getheaders():
        if name.lower()=='set-cookie':cookies.load(value)
    status=response.status;location=response.getheader('Location');content=response.read();connection.close()
    if status in {301,302,303,307,308} and method=='GET' and location and location.startswith('/'):
        return request('GET',location)
    return status,content
status,html=request('GET','/login');assert status==200
parser=Inputs();parser.feed(html.decode());assert parser.token
status,_=request('POST','/login',urlencode({'username':'demo@healthtracker.test','password':password,'csrf_token':parser.token}))
assert status==302,'login_failed'
paths=['/dashboard?from=2026-10-01&to=2026-10-31','/dashboard?from=2026-11-01&to=2026-11-18',
       '/energy?date=2026-11-18&period=90','/nutrition/?date=2026-11-18&period=90','/gym','/training-sessions','/progress']
statuses={}
for path in paths:
    status,html=request('GET',path)
    assert status==200 and b'name="password"' not in html,path
    statuses[path]=status
app=create_app()
with app.app_context():
    owner=db.session.scalar(db.select(User).where(User.email=='demo@healthtracker.test'))
    days=db.session.scalars(db.select(DailyNutrition).where(DailyNutrition.user_id==owner.id)).all()
    balances=[daily_balance(owner.id,day.date) for day in days]
    assert len(balances)==49 and all(b['complete'] and b['balance']==b['calories_consumed']-b['calories_expended'] for b in balances)
    foreign=db.session.scalar(db.select(TrainingSession.id).where(TrainingSession.user_id!=owner.id).limit(1))
    isolation='no_foreign_session_available'
    if foreign:
        assert request('GET','/training-sessions/'+str(foreign))[0]==404
        isolation='foreign_session_404'
    print(json.dumps({'login':'pass','http':statuses,'paired_days':len(balances),'canonical_balance':'pass','isolation':isolation}))
'''


def payload():
    return json.dumps({"password": os.environ["DEMO_USER_PASSWORD"]})
