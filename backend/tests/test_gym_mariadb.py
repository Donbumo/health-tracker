"""Explicit opt-in gate; never operates on an ordinary application schema."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db
from app.models import TrainingSession, TrainingSet, TrainingPlan, User
from app.services.gym_programs import confirm_program, preset_draft, preview_token, resolve_draft, activate_program
from app.services.gym_sessions import complete_set, finish_session, start_session, workout_context
from app.services.training_plans import get_active_version


@pytest.mark.skipif(not os.environ.get('GYM_QA_MARIADB'), reason='Explicit isolated MariaDB QA schema required')
def test_mariadb_program_set_start_concurrency_and_cascades(tmp_path):
    uri = os.environ['GYM_QA_MARIADB']
    assert make_url(uri).database == 'gym_training_2_qa_20260913'
    from pathlib import Path
    application = create_app({'TESTING':True, 'SECRET_KEY':'fictional-gym-mariadb-qa-secret-only',
        'SQLALCHEMY_DATABASE_URI':uri, 'DATA_ROOT':tmp_path, 'UPLOAD_ROOT':tmp_path/'uploads/raw',
        'GENERATED_UPLOAD_ROOT':tmp_path/'uploads/generated', 'SCHEMA_ROOT':Path(__file__).resolve().parents[2]/'schemas',
        'AI_ENABLED':False, 'WTF_CSRF_ENABLED':True})
    with application.app_context():
        user = User(username='gym-mariadb-qa-' + uuid.uuid4().hex, role='user')
        user.set_password('fictional-only-password')
        db.session.add(user); db.session.commit(); owner = user.id
        draft = resolve_draft(preset_draft('ppl-v1'), owner)
        plan, _ = confirm_program(draft, owner, preview_token(draft, owner))
        db.session.commit()
        version = get_active_version(plan, owner)
        plan_id, version_id = plan.public_id, version.public_id
    submission = str(uuid.uuid4())
    barrier = Barrier(2)
    def begin():
        with application.app_context():
            barrier.wait(timeout=10)
            row = start_session(owner, plan_id, version_id, 1, 1, submission)
            db.session.commit()
            return row.public_id
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: begin(), range(2)))
    assert results[0] == results[1]
    session_id = results[0]
    barrier = Barrier(2)
    def save():
        with application.app_context():
            barrier.wait(timeout=10)
            _, row, duplicate = complete_set(owner, session_id, 1, 1, {'load':'80','unit':'kg','reps':'8','rir':'2'})
            db.session.commit()
            return row.id, duplicate
    with ThreadPoolExecutor(max_workers=2) as executor:
        saved = list(executor.map(lambda _: save(), range(2)))
    assert saved[0][0] == saved[1][0]
    assert sorted(result[1] for result in saved) == [False, True]
    with application.app_context():
        assert db.session.query(TrainingSession).filter_by(user_id=owner).count() == 1
        assert db.session.query(TrainingSet).filter_by(user_id=owner).count() == 1
        row = finish_session(owner, session_id, 'completed')
        db.session.commit()
        row = start_session(owner, plan_id, version_id, 1, 1, str(uuid.uuid4()))
        db.session.commit()
        context = workout_context(row, owner, 'kg')
        assert context['exercises'][0]['sets'][0]['suggestion']['load'] == '80.00'
        assert context['completed_sets'] == 0
        assert db.session.query(TrainingPlan).filter_by(user_id=owner, gym_active=True).count() == 1
        db.session.execute(db.delete(User).where(User.id == owner)); db.session.commit()
        assert db.session.query(TrainingSet).filter_by(user_id=owner).count() == 0
        assert db.session.query(TrainingSession).filter_by(user_id=owner).count() == 0
        assert db.session.query(TrainingPlan).filter_by(user_id=owner).count() == 0
