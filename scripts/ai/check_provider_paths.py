"""Opt-in local QA of exactly two remote scenarios, with an ephemeral SQLite DB.

Run with the already configured app environment and the branch's app on PYTHONPATH.
Provider/model/timeouts are inherited unchanged. No retries, domain confirmations,
production database access, or raw output. All fixture/storage state is temporary.
"""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import AIActionDraft, User, UserGoal, WeighIn, NutritionItem
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import get_provider, provider_status
from app.services.engagement import create_goal


def main():
    with TemporaryDirectory(prefix="ht-deterministic-provider-qa-") as directory:
        root = Path(directory)
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "DATA_ROOT": root, "UPLOAD_ROOT": root / "raw",
            "GENERATED_UPLOAD_ROOT": root / "generated",
            "PORTABILITY_ROOT": root / "portability",
        })
        with app.app_context():
            status = provider_status()
            if status["state"] != "available" or not status["remote"]:
                print(json.dumps({"blocked": "configured_remote_provider_unavailable"}))
                return 2
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.create_all()
            user = User(username="ephemeral-provider-paths-qa", role="user", timezone="UTC",
                        ai_remote_consent_enabled=True)
            user.set_password("fictional-ephemeral-qa-password")
            db.session.add(user)
            db.session.commit()
            uid = user.id
            provider = get_provider()
            calls = []
            original_respond = provider.respond

            def observed(request):
                calls.append({"phase": request.phase,
                              "goals_read_first": any(result.name == "get_goals_summary" and result.ok
                                                      for result in request.tool_results)})
                return original_respond(request)

            provider.respond = observed
            app.config["AI_PROVIDER_INSTANCE"] = provider
            report = {}
            try:
                goal = create_goal(uid, {"goal_type": "daily_steps", "target_value": "9000",
                                       "unit": "step", "period": "daily", "timezone": "UTC",
                                       "start_date": date.today().isoformat()})
                db.session.commit()
                service = AIConversationService()
                for key, prompt in (
                    ("ambiguous", "Ajústame mis metas"),
                    ("proposal", "Revisa mis últimas semanas y proponme cambios en mis metas"),
                ):
                    calls.clear()
                    conversation = service.create(uid)
                    outcome = "valid_response"
                    try:
                        service.send_message(user, conversation.public_id, prompt)
                    except AIServiceError as error:
                        db.session.rollback()
                        outcome = error.code
                        assert AIActionDraft.query.filter_by(conversation_id=conversation.id).count() == 0
                    report[key] = {"provider_used": bool(calls), "result": outcome,
                                   "read_before_proposal": bool(calls and calls[0]["goals_read_first"])}
                    assert calls, "Expected provider path"
                    if key == "proposal":
                        assert calls[0]["phase"] == "proposal" and calls[0]["goals_read_first"]
                assert AIActionDraft.query.filter_by(user_id=uid, status="applied").count() == 0
                assert WeighIn.query.count() == NutritionItem.query.count() == 0
                assert db.session.get(UserGoal, goal.id).revision == 1
                report["silent_writes"] = 0
            finally:
                db.session.rollback()
                db.session.delete(db.session.get(User, uid))
                db.session.commit()
                assert db.session.get(User, uid) is None
                for mapper in db.Model.registry.mappers:
                    model = mapper.class_
                    if hasattr(model, "user_id"):
                        assert db.session.execute(db.select(db.func.count()).select_from(model)
                                                  .where(model.user_id == uid)).scalar_one() == 0
                report["qa_residues"] = 0
                db.session.remove()
                db.engine.dispose()
            print(json.dumps(report, sort_keys=True))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
