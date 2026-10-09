"""Disposable HTTP UI gate; synthetic data only, outside persistent storage."""
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from qa_app import build_app
from app.extensions import db
from app.services.gym_programs import preset_draft
from app.services.gym_sessions import complete_set, finish_session
from tests.test_gym_training import program, start
from app.models import User, TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, TrainingSession
from app import create_app
from app.services.exporters.training_session import build_completed_workout_document
from app.services.gym_capabilities import read_session

storage = Path(tempfile.mkdtemp(prefix='gym-delete-ui-'))
uri = os.environ.get('GYM_QA_MARIADB')
if uri:
    from sqlalchemy.engine import make_url
    assert make_url(uri).database == 'gym_training_2_qa_20260913'
    assert make_url(uri).host == '127.0.0.1' and make_url(uri).port == 33079
    app = create_app({'SECRET_KEY':'fictional-delete-ui-mariadb-secret-only',
        'SQLALCHEMY_DATABASE_URI':uri, 'DATA_ROOT':storage, 'UPLOAD_ROOT':storage/'raw',
        'GENERATED_UPLOAD_ROOT':storage/'generated', 'PORTABILITY_ROOT':storage/'portability',
        'SCHEMA_ROOT':ROOT/'schemas', 'AI_ENABLED':False, 'WTF_CSRF_ENABLED':True})
    with app.app_context():
        user = User(username='gym-qa', role='user')
        user.set_password('fictional-gym-qa-password')
        db.session.add(user)
        db.session.commit()
else:
    app = build_app(storage)
identities = {}
with app.app_context():
    owner = db.session.execute(db.select(User).where(User.username == 'gym-qa')).scalar_one().id
    for name, state in [('QA sin uso', None), ('QA historial', 'completed'), ('QA en curso', 'in_progress')]:
        draft = preset_draft('full-body-v1')
        draft.program['name'] = name
        plan = program(owner, draft)
        identities[name] = (plan.id, plan.public_id)
        if state:
            session = start(owner, plan)
            if state == 'completed':
                complete_set(owner, session.public_id, 1, 1, {'load':'20', 'unit':'kg', 'reps':'8', 'rir':'2'})
                finish_session(owner, session.public_id, state)
            db.session.commit()
            if state == 'completed':
                historical_id = session.id
                historical_snapshot = build_completed_workout_document(session, owner)


@app.get('/__qa/delete-gate')
def qa_gate():
    # This endpoint exists only in this disposable, loopback-only fixture server.
    unused_id, _ = identities['QA sin uso']
    historical_plan = db.session.get(TrainingPlan, identities['QA historial'][0])
    historical = db.session.get(TrainingSession, historical_id)
    return {
        'mariadb': bool(uri),
        'unused_removed': db.session.get(TrainingPlan, unused_id) is None,
        'unused_versions': db.session.query(TrainingPlanVersion).filter_by(training_plan_id=unused_id).count(),
        'unused_workouts': db.session.query(TrainingPlanWorkout).filter_by(training_plan_id=unused_id).count(),
        'historical_removed': historical_plan.deleted_at is not None,
        'historical_intact': build_completed_workout_document(historical, owner) == historical_snapshot,
        'ai_history_intact': read_session(owner, historical.public_id)['session_id'] == historical.public_id,
        'references_valid': historical.training_plan is not None and historical.training_plan_version is not None,
        'history_path': f'/training-sessions/{historical_id}',
    }

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8013, use_reloader=False)
