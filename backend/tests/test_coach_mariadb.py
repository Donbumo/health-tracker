"""Opt-in Coach/Operator gate on the disposable Gym progression MariaDB schema."""
import os

import pytest

from app.extensions import db
from app.models import TrainingPlanVersion, User
from app.services.ai.conversations import AIConversationService
from app.services.coach import CoachBriefService
from tests.test_gym_strength_mariadb import maria_app


pytestmark = pytest.mark.skipif(not os.environ.get("STRENGTH_QA_MARIADB"),
                                reason="Explicit disposable strength MariaDB required")


def test_mariadb_coach_brief_and_confirmed_operator(maria_app):
    app, (owner, program_id, _exercise_id, _session_id) = maria_app
    with app.app_context():
        account = db.session.get(User, owner)
        brief = CoachBriefService().build(account)["week"]
        assert any(signal["type"] == "progression_candidate" for signal in brief["signals"])
        before = db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count()
        service = AIConversationService()
        conversation = service.prepare_coach_progression(account, program_id, "1:1:1")
        draft_id = conversation.drafts[0].public_id
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count() == before
        service.confirm_draft(account, draft_id)
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count() == before + 1
        service.confirm_draft(account, draft_id)
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=owner).count() == before + 1
