"""D: real Flask, fictional A/B/C states and 10000 audit events; no NAS access."""
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
import sys,tempfile,uuid,hashlib,json,io
from werkzeug.serving import make_server
from werkzeug.datastructures import FileStorage
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,EnergyEvidenceEvent
from app.services import energy_days as energy
from app.services.files import store_uploaded_file
from tests.test_energy_experience import seed,DAY
from tests.test_energy_days import document
storage=Path(tempfile.mkdtemp(prefix='QA-energy-D-'))
app=create_app({'TESTING':True,'TEMPLATES_AUTO_RELOAD':True,'SECRET_KEY':'fictional-energy-D-cookie-key-only',
    'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(storage/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},
    'DATA_ROOT':storage,'UPLOAD_ROOT':storage/'uploads/raw','GENERATED_UPLOAD_ROOT':storage/'uploads/generated',
    'PORTABILITY_ROOT':storage/'portability','SCHEMA_ROOT':ROOT/'schemas','APP_TIMEZONE':'UTC',
    'NUTRITION_INTELLIGENCE_ENABLED':True,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,'AI_ENABLED':False})
with app.app_context():
    db.create_all();owner=User(username='QA-energy-D',display_name='QA ficticia D',role='user');owner.set_password('fictional-energy-D-password')
    other=User(username='QA-energy-D-other',role='user');other.set_password('fictional-energy-D-other-password');db.session.add_all([owner,other]);db.session.commit()
    seed(owner.id)
    original=document(owner.id,'QA original D',total_expenditure_kcal=2500)
    raw=json.dumps(original).encode()+b'\n'
    file,_=store_uploaded_file(FileStorage(stream=io.BytesIO(raw),filename='QA-D-original.json'),owner.id)
    energy.upsert_document(original,owner.id,source_file=file);db.session.commit()
    energy.edit_day(owner.id,DAY,energy.view(owner.id,DAY).revision,{'total_calories':2450});db.session.commit()
    energy.upsert_document(document(other.id,'QA ajeno no visible',total_expenditure_kcal=9999),other.id);db.session.commit()
    rows=[]
    for i in range(10000):
        rows.append({'user_id':owner.id,'date':DAY-timedelta(days=i%365),'evidence_public_id':str(uuid.uuid4()),
            'event_key':hashlib.sha256(('QA-D-audit-'+str(i)).encode()).hexdigest(),'kind':'import',
            'payload_json':{'record':{'source':'QA volumen '+str(i%5),'revision':1,'values':{'steps':i}}},
            'created_at':datetime(2000,1,1,tzinfo=timezone.utc)+timedelta(seconds=i)})
    db.session.execute(db.insert(EnergyEvidenceEvent),rows);db.session.commit()
if __name__=='__main__':
    server=make_server('127.0.0.1',0,app)
    print(json.dumps({'scope':'fictional D QA only; no NAS','url':f'http://127.0.0.1:{server.server_port}','synthetic_audit_events':10000}),flush=True)
    server.serve_forever()
