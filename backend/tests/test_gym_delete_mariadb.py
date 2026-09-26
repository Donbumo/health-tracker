"""Explicit isolated MariaDB gate for DELETE/FK locks and transaction rollback."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db
from app.models import (TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout,
                        TrainingSession, SyncChange, User, PlannedWorkout,
                        WorkoutSessionDraft, TrainingSet)
from app.services.gym_delete import (
    delete_program,
    discard_pending_draft,
    discard_pending_planned,
    discard_pending_session,
)
from app.services.gym_programs import GymError
from app.services.gym_sessions import start_session
from app.services.mobile_sync import PlannedWorkoutService
from app.services.training_plans import get_active_version
from tests.test_gym_training import program


@pytest.fixture
def maria(tmp_path):
    uri = os.environ.get('GYM_QA_MARIADB')
    if not uri:
        pytest.skip('Explicit isolated MariaDB QA schema required')
    qa_url = make_url(uri)
    assert qa_url.database == 'gym_training_2_qa_20260913'
    expected_host = os.environ.get('GYM_QA_MARIADB_EXPECTED_HOST', '127.0.0.1')
    expected_port = int(os.environ.get('GYM_QA_MARIADB_EXPECTED_PORT', '33079'))
    assert qa_url.host == expected_host and qa_url.port == expected_port
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


def test_mariadb_historical_removal_rollback_and_replay(maria, monkeypatch):
    from app.services.gym_sessions import complete_set, finish_session
    from app.services.exporters.training_session import build_completed_workout_document
    application, (owner, public_id, revision, version_id) = maria
    with application.app_context():
        row = start_session(owner, public_id, version_id, 1, 1, str(uuid.uuid4()))
        complete_set(owner, row.public_id, 1, 1, {'load':'42.5','unit':'kg','reps':'7','rir':'2'})
        finish_session(owner, row.public_id, 'completed')
        db.session.commit()
        snapshot = build_completed_workout_document(row, owner)
        with monkeypatch.context() as patch:
            def fail(**kwargs):
                raise RuntimeError('fictional historical rollback gate')
            patch.setattr('app.services.gym_delete.record_sync_change', fail)
            with pytest.raises(RuntimeError):
                delete_program(owner, public_id, base_revision=revision, confirmation='ELIMINAR')
            db.session.rollback()
        plan = db.session.query(TrainingPlan).filter_by(user_id=owner).one()
        assert plan.deleted_at is None
        assert db.session.query(TrainingPlanWorkout).filter_by(user_id=owner).count() == 3
        for expected in (True, False):
            assert delete_program(owner, public_id, base_revision=revision, confirmation='ELIMINAR') is expected
            db.session.commit()
        assert build_completed_workout_document(row, owner) == snapshot
        assert plan.deleted_at is not None
        assert db.session.query(TrainingPlanWorkout).filter_by(user_id=owner).count() == 0
        assert db.session.query(SyncChange).filter_by(user_id=owner, operation='delete').count() == 1


def test_mariadb_pending_artifacts_are_resolved_individually(maria):
    from app.services.gym_sessions import complete_set

    application, (owner, public_id, revision, version_id) = maria
    with application.app_context():
        plan = db.session.query(TrainingPlan).filter_by(public_id=public_id).one()
        draft = WorkoutSessionDraft(
            user_id=owner,
            training_plan_id=plan.id,
            training_plan_version_id=plan.versions[0].id,
            client_submission_id=str(uuid.uuid4()),
            payload_json={"fictional": "mariadb pending draft"},
            payload_hash="0" * 64,
            expires_at=datetime.now(timezone.utc),
        )
        db.session.add(draft)
        session = start_session(owner, public_id, version_id, 1, 1, str(uuid.uuid4()))
        complete_set(owner, session.public_id, 1, 1,
                    {"load": "35", "unit": "kg", "reps": "8", "rir": "2"})
        agenda = PlannedWorkoutService.schedule_from_plan_version(
            user_id=owner,
            plan_public_id=public_id,
            version_public_id=None,
            scheduled_for_date=date(2026, 9, 18),
            timezone_name="UTC",
            week_number=1,
            day_number=1,
        )
        db.session.commit()
        with pytest.raises(GymError, match="sesi\u00f3n pendiente"):
            delete_program(owner, public_id, base_revision=revision, confirmation="ELIMINAR")
        db.session.rollback()

        with pytest.raises(GymError, match="DESCARTAR"):
            discard_pending_session(owner, public_id, session.public_id, confirmation="NO")
        db.session.rollback()
        discard_pending_draft(owner, public_id, draft.public_id, confirmation="DESCARTAR")
        db.session.commit()
        discard_pending_session(owner, public_id, session.public_id, confirmation="DESCARTAR")
        db.session.commit()
        discard_pending_planned(owner, public_id, agenda.public_id, confirmation="DESCARTAR")
        db.session.commit()
        assert db.session.query(TrainingSet).filter_by(user_id=owner).count() == 0
        assert db.session.query(WorkoutSessionDraft).filter_by(user_id=owner).count() == 0
        assert db.session.query(PlannedWorkout).filter_by(user_id=owner, deleted_at=None).count() == 0
        assert delete_program(owner, public_id, base_revision=revision, confirmation="ELIMINAR")
        db.session.commit()
        assert db.session.query(TrainingPlan).filter_by(public_id=public_id).one().deleted_at is not None


@pytest.mark.parametrize('action', [None, 'preserve', 'discard'])
def test_mariadb_integral_real_route(maria, monkeypatch, action):
    from tests.test_gym_delete_integral import integral_gate
    application, (owner, _, _, _) = maria
    with application.app_context():
        integral_gate(application, owner, partial=action is not None,
                      action=action, rollback_patch=monkeypatch)


def test_mariadb_integral_concurrent_retry(maria):
    from tests.test_gym_delete_integral import seed
    from app.services.gym_delete import deletion_preview
    application, (owner, _, _, _) = maria
    with application.app_context():
        plan, _, _, _, _, _ = seed(owner)
        public_id, revision = plan.public_id, plan.revision
        token = deletion_preview(plan)['token']
    barrier = Barrier(2)
    def operation(_):
        with application.app_context():
            barrier.wait(timeout=10)
            result = delete_program(owner, public_id, base_revision=revision,
                                    confirmation='ELIMINAR', pending_token=token)
            db.session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(operation, [0, 1])) == [False, True]
    with application.app_context():
        assert db.session.query(TrainingSession).filter_by(user_id=owner).count() == 1
        assert db.session.query(WorkoutSessionDraft).filter_by(user_id=owner).count() == 0
        assert db.session.query(SyncChange).filter_by(user_id=owner, operation='delete').count() == 2
