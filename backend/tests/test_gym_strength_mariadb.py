"""Opt-in isolated MariaDB: real locks, stale snapshots, rollback and concurrency."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from app import create_app
from app.extensions import db
from app.models import User, TrainingPlanVersion, TrainingSession
from app.services.gym_progression_confirm import preview,confirm
from app.services.gym_strength import StrengthReader
from app.services.gym_programs import GymError
from tests.gym_strength_fixtures import strength_fixture

pytestmark=pytest.mark.skipif(not os.environ.get("STRENGTH_QA_MARIADB"),reason="Explicit disposable strength MariaDB required")

@pytest.fixture(params=["READ COMMITTED", "REPEATABLE READ"])
def maria_app(tmp_path, request):
    uri=os.environ["STRENGTH_QA_MARIADB"]
    parsed=make_url(uri)
    assert parsed.database=="gym_progression_qa" and parsed.host=="127.0.0.1" and parsed.port==33381
    app=create_app({"TESTING":True,"SECRET_KEY":"fictional-strength-mariadb-qa-secret-only",
        "SQLALCHEMY_DATABASE_URI":uri,"SQLALCHEMY_ENGINE_OPTIONS":{"isolation_level":request.param},
        "DATA_ROOT":tmp_path,"UPLOAD_ROOT":tmp_path/"raw",
        "GENERATED_UPLOAD_ROOT":tmp_path/"generated","PORTABILITY_ROOT":tmp_path/"portability",
        "SCHEMA_ROOT":Path(__file__).resolve().parents[2]/"schemas","AI_ENABLED":False})
    with app.app_context():
        user=User(username="qa-lock-"+uuid4().hex,role="user");user.set_password("fictional-password")
        db.session.add(user);db.session.commit();owner=user.id
        plan,identities,sessions=strength_fixture(owner)
        ids=(owner,plan.public_id,identities[0].public_id,sessions[-1].public_id)
    yield app,ids
    with app.app_context():
        db.session.execute(db.delete(User).where(User.id==ids[0]));db.session.commit()

def test_concurrent_confirm_only_one_revision(maria_app):
    app,(owner,plan,exercise,session)=maria_app
    with app.app_context(): token=preview(owner,plan,"1:1:1")["token"]
    barrier=Barrier(2)
    def apply():
        with app.app_context():
            # Intentionally establish an old REPEATABLE READ snapshot.
            db.session.get(User,owner)
            barrier.wait(timeout=10)
            result=confirm(owner,token);db.session.commit()
            return result[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:apply(),range(2)))
    assert sorted(results)==[False,True]
    with app.app_context():
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count()==2

def test_changed_evidence_is_seen_after_old_snapshot(maria_app):
    app,(owner,plan,exercise,session)=maria_app
    with app.app_context():
        token=preview(owner,plan,"1:1:1")["token"]
        def edit():
            with app.app_context():
                record=db.session.execute(db.select(TrainingSession).where(TrainingSession.public_id==session).with_for_update()).scalar_one()
                record.exercises[0].sets[0].reps=6
                record.revision+=1;db.session.commit()
        with ThreadPoolExecutor(max_workers=1) as pool: pool.submit(edit).result(timeout=10)
        with pytest.raises(GymError) as error: confirm(owner,token)
        assert error.value.status==409
        db.session.rollback()

def test_confirmation_rollback_is_atomic(maria_app):
    app,(owner,plan,exercise,session)=maria_app
    with app.app_context():
        token=preview(owner,plan,"1:1:1")["token"]
        confirm(owner,token)
        db.session.rollback()
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count()==1
        reader=StrengthReader(owner)
        assert reader.evaluate(reader.context(plan,"1:1:1"))["current"]["load"]=="80.00"
