"""Disposable synthetic HTTP fixtures; never load production configuration."""
import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from tests.test_gym_delete_integral import seed
from sqlalchemy.engine import make_url

storage = Path(tempfile.mkdtemp(prefix='gym-delete-pending-ui-'))
uri = os.environ.get('GYM_QA_MARIADB', 'sqlite://')
if uri != 'sqlite://':
    assert make_url(uri).database == 'gym_training_2_qa_20260913'
    assert make_url(uri).host in ('db', '127.0.0.1')
app = create_app({'SECRET_KEY':'fictional-pending-ui-secret-only',
    'SQLALCHEMY_DATABASE_URI':uri, 'DATA_ROOT':storage, 'UPLOAD_ROOT':storage/'raw',
    'GENERATED_UPLOAD_ROOT':storage/'generated', 'PORTABILITY_ROOT':storage/'portability',
    'SCHEMA_ROOT':ROOT/'schemas', 'AI_ENABLED':False, 'WTF_CSRF_ENABLED':True})
with app.app_context():
    if uri == 'sqlite://':
        db.create_all()
    user = User(username='pending-qa', role='user')
    user.set_password('fictional-pending-qa-password')
    db.session.add(user)
    db.session.commit()
    for name, partial in [('QA integral', False), ('QA parcial', True), ('QA individual', True)]:
        seed(user.id, name=name, partial=partial)
if __name__ == '__main__':
    # Container port is published on loopback only by the disposable QA compose.
    app.run(host=os.environ.get('GYM_QA_BIND', '127.0.0.1'), port=8014, use_reloader=False)
