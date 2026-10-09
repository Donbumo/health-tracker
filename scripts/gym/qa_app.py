"""Disposable local visual QA app. Uses synthetic fixtures and separate storage."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.services.gym_programs import confirm_program, preview_token, resolve_draft
from app.services.importers.routine_draft import DeterministicParser


def build_app(storage):
    storage = Path(storage).resolve()
    app = create_app({'SECRET_KEY':'fictional-gym-qa-local-secret-key-only',
        'API_TOKEN_SIGNING_KEY':'fictional-gym-qa-local-api-key-only',
        'SQLALCHEMY_DATABASE_URI':'sqlite:///' + str(storage / 'qa.sqlite'),
        'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': storage,
        'UPLOAD_ROOT':storage/'uploads/raw', 'GENERATED_UPLOAD_ROOT':storage/'uploads/generated',
        'PORTABILITY_ROOT':storage/'portability', 'SCHEMA_ROOT': ROOT/'schemas',
        'APP_TIMEZONE':'America/Mexico_City', 'SESSION_COOKIE_SECURE':False,
        'AI_ENABLED':False, 'TESTING':False})
    with app.app_context():
        db.create_all()
        user = db.session.execute(db.select(User).where(User.username == 'gym-qa')).scalar_one_or_none()
        if user is None:
            user = User(username='gym-qa', role='user', timezone='America/Mexico_City', preferred_load_unit='kg')
            user.set_password('fictional-gym-qa-password')
            db.session.add(user); db.session.commit()
            source = ROOT/'backend/tests/fixtures/gym_qa/routine.csv'
            draft = DeterministicParser().parse(source.read_bytes(), 'routine.csv', 'QA · Gym Training 2.0')
            for day in draft.days:
                for exercise in day['exercises']: exercise['create_new'] = True
            resolve_draft(draft, user.id)
            confirm_program(draft, user.id, preview_token(draft, user.id))
            db.session.commit()
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--storage', default=None)
    parser.add_argument('--port', type=int, default=8011)
    args = parser.parse_args()
    storage = args.storage or tempfile.mkdtemp(prefix='health-tracker-gym-qa-')
    Path(storage).mkdir(parents=True, exist_ok=True)
    print(json.dumps({'qa_storage':storage, 'port':args.port}), flush=True)
    build_app(storage).run(host='127.0.0.1', port=args.port, use_reloader=False)
