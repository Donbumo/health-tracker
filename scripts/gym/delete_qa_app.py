"""Disposable HTTP UI gate; synthetic data only, outside persistent storage."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from qa_app import build_app
from app.extensions import db
from app.services.gym_programs import preset_draft
from app.services.gym_sessions import complete_set, finish_session
from tests.test_gym_training import program, start
from app.models import User

app = build_app(Path(tempfile.mkdtemp(prefix='gym-delete-ui-')))
with app.app_context():
    owner = db.session.execute(db.select(User).where(User.username == 'gym-qa')).scalar_one().id
    for name, state in [('QA sin uso', None), ('QA historial', 'completed'), ('QA en curso', 'in_progress')]:
        draft = preset_draft('full-body-v1')
        draft.program['name'] = name
        plan = program(owner, draft)
        if state:
            session = start(owner, plan)
            if state == 'completed':
                complete_set(owner, session.public_id, 1, 1, {'load':'20', 'unit':'kg', 'reps':'8', 'rir':'2'})
                finish_session(owner, session.public_id, state)
            db.session.commit()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8013, use_reloader=False)
