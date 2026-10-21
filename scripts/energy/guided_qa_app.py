"""C real Flask with shared synthetic provenance fixtures; no NAS access."""
from pathlib import Path
from datetime import timedelta
import sys
import tempfile
import json
from werkzeug.serving import make_server

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services import energy_days
from tests.test_energy_provenance import seed, DAY
from tests.test_energy_days import document

storage=Path(tempfile.mkdtemp(prefix='QA-energy-B-'))
app=create_app({'TESTING':True,'TEMPLATES_AUTO_RELOAD':True,
    'SECRET_KEY':'fictional-energy-provenance-cookie-key-only',
    'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(storage/'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS':{},'DATA_ROOT':storage,'UPLOAD_ROOT':storage/'uploads/raw',
    'GENERATED_UPLOAD_ROOT':storage/'uploads/generated','PORTABILITY_ROOT':storage/'portability',
    'SCHEMA_ROOT':ROOT/'schemas','NUTRITION_INTELLIGENCE_ENABLED':False,
    'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False,'AI_ENABLED':False})
with app.app_context():
    db.create_all();owner=User(username='QA-energy-provenance',role='user',display_name='QA ficticia C')
    owner.set_password('fictional-energy-provenance-password');db.session.add(owner);db.session.commit()
    fixture=seed(owner.id)
    other=db.session.get(User,fixture['other']);other.username='QA-energy-provenance-other'
    other.set_password('fictional-energy-provenance-other-password');db.session.commit()
    for offset in range(110):
        energy_days.upsert_document(document(owner.id,'QA historial',day=DAY-timedelta(days=offset+1),steps=offset),owner.id)
    db.session.commit()
    # Retired entire day, with original and decisions retained, separate from the
    # active source example used for before/after navigation.
    retired=DAY-timedelta(days=1)
    energy_days.delete_day(owner.id,retired,energy_days.view(owner.id,retired).revision);db.session.commit()
    proposed=DAY+timedelta(days=1)
    for value in [2100,2200]:
        energy_days.upsert_document(document(owner.id,'QA propuesta',day=proposed,total_expenditure_kcal=value),owner.id)
    db.session.commit()

if __name__=='__main__':
    server=make_server('127.0.0.1',0,app)
    print(json.dumps({'scope':'fictional C QA only','url':f'http://127.0.0.1:{server.server_port}'}),flush=True)
    server.serve_forever()
