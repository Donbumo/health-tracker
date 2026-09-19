"""Explicit isolated MariaDB gate for DELETE/FK locks and transaction rollback."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import uuid

import pytest
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, TrainingSession, SyncChange, User
from app.services.gym_delete import delete_program
from app.services.gym_programs import GymError
from app.services.gym_sessions import start_session
from app.services.training_plans import get_active_version
from tests.test_gym_training import program


@pytest.fixture
def maria(tmp_path):
    uri = os.environ.get('GYM_QA_MARIADB')
    if not uri:
        pytest.skip('Explicit isolated MariaDB QA schema required')
    assert make_url(uri).database == 'gym_training_2_qa_20260913'
    application = create_app({'TESTING':True, 'SECRET_KEY':'fictional-delete-mariadb-qa-secret',
        'SQLALCHEMY_DATABASE_URI':uri, 'DATA_ROOT':tmp_path,
        'UPLOAD_ROOT':tmp_path/'uploads/raw', 'GENERATED_UPLOAD_ROOT':tmp_path/'uploads/generated',
        'PORTABILITY_ROOT':tmp_path/'portability', 'SCHEMA_ROOT':Path(__file__).resolve().parents[2]/'schemas',
        'AI_ENABLED':False})
    with application.app_context():
        owner = User(username='delete-qa-' + uuid.uuid4().hex, role='user')
        owner.set_password('fictional-only-password')
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id
        plan = program(owner_id)
        ids = owner_id, plan.public_id, plan.revision, get_active_version(plan, owner_id).public_id
    try:
        yield application, ids
    finally:
        with application.app_context():
            db.session.execute(db.delete(User).where(User.id == owner_id))
            db.session.commit()


@pytest.mark.parametrize('race', ['delete_delete', 'delete_start'])
def test_mariadb_delete_races(maria, race):
    application, (owner, public_id, revision, version_id) = maria
    barrier = Barrier(2)
    def operation(index):
        with application.app_context():
            barrier.wait(timeout=10)
            try:
                if index == 1 and race == 'delete_start':
                    start_session(owner, public_id, version_id, 1, 1, str(uuid.uuid4()))
                    result = 'started'
                else:
                    result = 'deleted' if delete_program(owner, public_id, base_revision=revision, confirmation='ELIMINAR') else 'replay'
                db.session.commit()
                return result
            except GymError as error:
                db.session.rollback()
                return error.status
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(operation, [0, 1]))
    with application.app_context():
        plans = db.session.query(TrainingPlan).filter_by(user_id=owner).count()
        sessions = db.session.query(TrainingSession).filter_by(user_id=owner).count()
        tombstones = db.session.query(SyncChange).filter_by(user_id=owner, operation='delete').count()
        if race == 'delete_delete':
            assert sorted(outcomes) == ['deleted', 'replay']
            assert (plans, sessions, tombstones) == (0, 0, 1)
        elif 'started' in outcomes:
            assert outcomes == [409, 'started']
            assert (plans, sessions, tombstones) == (1, 1, 0)
        else:
            assert outcomes == ['deleted', 404]
            assert (plans, sessions, tombstones) == (0, 0, 1)
        if not plans:
            for model in (TrainingPlanVersion, TrainingPlanWorkout):
                assert db.session.query(model).filter_by(user_id=owner).count() == 0


def test_mariadb_rollback_restores_cascaded_children(maria, monkeypatch):
    application, (owner, public_id, revision, _) = maria
    with application.app_context():
        def fail(**kwargs):
            raise RuntimeError('fictional rollback gate')
        monkeypatch.setattr('app.services.gym_delete.record_sync_change', fail)
        with pytest.raises(RuntimeError):
            delete_program(owner, public_id, base_revision=revision, confirmation='ELIMINAR')
        db.session.rollback()
        assert db.session.query(TrainingPlan).filter_by(user_id=owner).count() == 1
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count() == 1
        assert db.session.query(TrainingPlanWorkout).filter_by(user_id=owner).count() == 3
        assert db.session.query(SyncChange).filter_by(user_id=owner, operation='delete').count() == 0
