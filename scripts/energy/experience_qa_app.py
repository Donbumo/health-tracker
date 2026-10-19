"""Real Flask, temporary SQLite, synthetic owners only. No persistent config."""
import json
from pathlib import Path
import sys
import tempfile
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from tests.test_energy_experience import seed

storage = Path(tempfile.mkdtemp(prefix='QA-energy-experience-A-'))
app = create_app({'TESTING': True, 'SECRET_KEY': 'fictional-energy-experience-review-cookie-key',
    'TEMPLATES_AUTO_RELOAD': True,
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (storage/'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': storage, 'SCHEMA_ROOT': ROOT/'schemas',
    'UPLOAD_ROOT': storage/'uploads/raw', 'GENERATED_UPLOAD_ROOT': storage/'uploads/generated',
    'PORTABILITY_ROOT': storage/'portability',
    'NUTRITION_INTELLIGENCE_ENABLED': False, 'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False,
    'AI_ENABLED': False})
with app.app_context():
    db.create_all()
    owner = User(username='QA-energy-experience',role='user',display_name='QA ficticia')
    owner.set_password('fictional-energy-experience-password')
    db.session.add(owner); db.session.commit()
    seed(owner.id)

if __name__ == '__main__':
    server = make_server('127.0.0.1', 0, app)
    print(json.dumps({'scope':'synthetic QA only','url':f'http://127.0.0.1:{server.server_port}'}),flush=True)
    server.serve_forever()
