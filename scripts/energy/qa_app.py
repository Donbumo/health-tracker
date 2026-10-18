"""Real Flask/Jinja, ephemeral SQLite, fictional owners only. Reuses QA :8025."""
import json
from pathlib import Path
import sys
import tempfile
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services import energy_days as energy

storage = Path(tempfile.mkdtemp(prefix='QA-energy18-ui-'))
app = create_app({'TESTING': True, 'SECRET_KEY': 'fictional-energy18-qa-cookie-key-only',
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (storage/'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': storage, 'SCHEMA_ROOT': ROOT/'schemas',
    'UPLOAD_ROOT': storage/'uploads/raw', 'GENERATED_UPLOAD_ROOT': storage/'uploads/generated',
    'NUTRITION_INTELLIGENCE_ENABLED': False, 'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False,
    'AI_ENABLED': False})
with app.app_context():
    db.create_all()
    owner = User(username='QA-energy18', role='user', display_name='QA ficticia')
    owner.set_password('fictional-energy18-qa-password')
    db.session.add(owner);db.session.commit()
    for day, source, values in [
        ('2040-02-03', 'QA pasos', {'steps':1200, 'distance_meters':800}),
        ('2040-02-03', 'QA dispositivo', {'total_expenditure_kcal':2400, 'active_expenditure_kcal':600, 'resting_expenditure_kcal':1800, 'steps':1200}),
        ('2040-02-04', 'QA fuente A', {'total_expenditure_kcal':2200, 'steps':1000}),
        ('2040-02-04', 'QA fuente B', {'total_expenditure_kcal':2300, 'steps':1000}),
    ]:
        energy.upsert_document({'schema_version':'1.0','record_type':'daily_energy','user_id':owner.id,
            'source_type':'uploaded','data':{'date':day,'source':source, **values}},owner.id)
    db.session.commit()
    print(json.dumps({'scope':'fictional QA','records':{row.date.isoformat():row.id for row in energy.views(owner.id)}}),flush=True)

if __name__ == '__main__':
    app.run(host='127.0.0.1',port=8025,use_reloader=False,debug=False)
