"""Coach contracts use fictional fixture accounts and never touch real health data."""
import pytest
from sqlalchemy import event
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import AIActionDraft, DailyEnergy, DailyNutrition, TrainingPlan, TrainingPlanVersion, User
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import AIIntentSpec, AIIntent
from app.services.ai.capabilities.types import CapabilityError
from app.services.ai.conversations import AIConversationService, AIServiceError, serialize_draft
from app.services.ai.providers import AIProviderError, FakeAIProvider
from app.services.ai.tools import AIToolRegistry
from app.services.ai.types import AIProviderResponse
from app.services.coach import CoachBriefService, CoachSignalEngine
from app.services.training_plans import get_active_version
from app.services.engagement import create_goal
from tests.gym_strength_fixtures import strength_fixture
from tests.conftest import login


def test_empty_coach_briefs_are_evidence_backed_and_bounded(app, user):
    with app.app_context():
        account = db.session.get(User, user)
        briefs = CoachBriefService().build(account)
        for key in ("today", "week"):
            brief = briefs[key]
            assert 1 <= len(brief["top_priorities"]) <= 5
            assert brief["period"] and brief["generated_at"]
            assert all(signal["evidence"] and signal["coverage"] for signal in brief["signals"])
            assert all(signal["action"] is None for signal in brief["signals"])


def test_coach_ranking_is_deterministic_and_deduplicated():
    period = {"preset": "7d", "from": "2026-10-01", "to": "2026-10-07", "timezone": "UTC", "days": 7}
    evidence = ({"label": "QA", "value": 1, "source": "fictional fixture", "period": period},)
    low = CoachSignalEngine._signal(period=period, domain="activity", kind="review", metric="steps",
                                    title="QA low", message="QA", evidence=evidence, severity="low")
    high = CoachSignalEngine._signal(period=period, domain="gym", kind="review", metric="reps",
                                     title="QA high", message="QA", evidence=evidence, severity="high")
    assert CoachSignalEngine._rank([low, high, low]) == [high, low]
    many = [CoachSignalEngine._signal(period=period, domain="gym", kind="review",
             metric=f"exercise_{index}", title="QA gym", message="QA", evidence=evidence,
             severity="high") for index in range(8)]
    other = CoachSignalEngine._signal(period=period, domain="nutrition", kind="review",
             metric="energy", title="QA nutrition", message="QA", evidence=evidence,
             severity="medium")
    brief = CoachSignalEngine._brief(period, many + [other], datetime.now())
    assert len(brief["top_priorities"]) == 5
    assert any(signal["domain"] == "nutrition" for signal in brief["top_priorities"])


def test_coach_intents_and_owner_only_ui(app, client, user):
    with app.app_context():
        registry = AICapabilityRegistry()
        for intent, period in (("daily_coach", "today"), ("weekly_coach", "7d"),
                               ("explain_signal", "7d"), ("explain_progression", "7d"),
                               ("what_changed", "7d"), ("what_should_i_review", "7d")):
            spec = registry.parse({"intent": intent, "domain": "all", "period": period})
            assert registry.resolve(spec).tools == ("get_coach_brief",)
        with pytest.raises(CapabilityError):
            registry.parse({"intent": "correct", "domain": "training", "period": "today",
                            "action": "training.progression.update"})
        assert "training.progression.update" not in {
            item.action_capability_id for item in registry.provider_action_definitions()}
    assert client.get("/ai").status_code in (302, 401)
    login(client)
    for path in ("/ai", "/today", "/dashboard"):
        response = client.get(path)
        assert response.status_code == 200, response.data[:500]
        assert b"Coach" in response.data or b"Resumen de hoy" in response.data


def test_coach_reuses_gym_engine_and_operator_requires_confirmation(app, client, user):
    with app.app_context():
        plan, _, _ = strength_fixture(user)
        account = db.session.get(User, user)
        brief = CoachBriefService().build(account)["week"]
        candidate = next(item for item in brief["signals"] if item["type"] == "progression_candidate")
        assert candidate["action"]["capability"] == "training.progression.update"
        assert candidate["current"] == "80.00"
        assert candidate["baseline"] is None
        assert any(item["label"] == "Propuesta sin aplicar" for item in candidate["evidence"])
        before = db.session.query(TrainingPlanVersion).filter_by(user_id=user).count()
        program_id = plan.public_id
    login(client)
    endpoint = f"/ai/coach/progression/{program_id}/1:1:1/prepare"
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(endpoint).status_code == 400
    app.config["WTF_CSRF_ENABLED"] = False
    response = client.post(endpoint)
    assert response.status_code == 302
    with app.app_context():
        draft = db.session.query(AIActionDraft).filter_by(user_id=user).one()
        assert draft.status == "pending_confirmation"
        assert draft.provenance_json["action_capability_id"] == "training.progression.update"
        assert "_coach_source_hash" in draft.provenance_json
        assert "_coach_source_hash" not in str(serialize_draft(draft))
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == before
        draft_id, conversation_id = draft.public_id, draft.conversation.public_id
    page = client.get(f"/ai/conversations/{conversation_id}")
    assert page.status_code == 200 and "82.50" in page.text
    response = client.post(f"/ai/drafts/{draft_id}/confirm", data={"conversation_id": conversation_id})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == before + 1
        refreshed = db.session.query(TrainingPlan).filter_by(user_id=user, public_id=program_id).one()
        assert get_active_version(refreshed, user).content["data"]["weeks"][0]["days"][0]["exercises"][0]["sets"][0]["load_value"] == "82.50"
        assert db.session.query(AIActionDraft).filter_by(user_id=user).one().status == "applied"
    client.post(f"/ai/drafts/{draft_id}/confirm", data={"conversation_id": conversation_id})
    with app.app_context():
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == before + 1


def test_coach_operator_rejects_other_owner_and_stale_evidence(app, user):
    with app.app_context():
        plan, _, sessions = strength_fixture(user)
        other = User(username="fictional-other-coach", role="user")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.commit()
        service = AIConversationService()
        with pytest.raises(AIServiceError) as error:
            service.prepare_coach_progression(other, plan.public_id, "1:1:1")
        assert error.value.status == 404
        conversation = service.prepare_coach_progression(db.session.get(User, user), plan.public_id, "1:1:1")
        draft_id = conversation.drafts[0].public_id
        sessions[-1].exercises[0].sets[0].reps = 6
        db.session.commit()
        with pytest.raises(AIServiceError) as error:
            service.confirm_draft(db.session.get(User, user), draft_id)
        assert error.value.status == 409
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == 1


def test_coach_operator_rejects_changed_source_even_if_visible_evidence_is_same(app, user):
    with app.app_context():
        plan, _, sessions = strength_fixture(user)
        account = db.session.get(User, user)
        service = AIConversationService()
        conversation = service.prepare_coach_progression(account, plan.public_id, "1:1:1")
        draft_id = conversation.drafts[0].public_id
        sessions[-1].revision += 1
        db.session.commit()
        with pytest.raises(AIServiceError) as error:
            service.confirm_draft(account, draft_id)
        assert error.value.code == "revision_conflict"
        assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == 1


def test_coach_fake_summary_uses_server_read_and_disabled_provider_keeps_brief(app, client, user):
    login(client)
    disabled = client.get("/ai")
    assert disabled.status_code == 200
    assert "Resumen generado con datos de Health Tracker" in disabled.text
    with app.app_context():
        account = db.session.get(User, user)
        tool = AIToolRegistry().execute(account, "get_coach_brief", {"preset": "7d"})
        assert tool.data["signals"] and tool.evidence
        gym_only = AIToolRegistry().execute(account, "get_coach_brief",
                                             {"preset": "7d", "progression_only": True})
        assert all(item["domain"] == "gym" for item in gym_only.data["signals"])
        app.config.update(AI_ENABLED=True, AI_PROVIDER="fake", AI_MODEL="fake-health-v1",
                          AI_PROVIDER_INSTANCE=FakeAIProvider(), AI_RATE_LIMIT_ENABLED=False)
        service = AIConversationService()
        conversation = service.create(user, title="Coach QA ficticio")
        answer, drafts = service.send_message(account, conversation.public_id,
            "Resume las señales con evidencia", intent_spec=AIIntentSpec(AIIntent.WEEKLY_COACH, "all", period="7d"))
        assert answer.content and not drafts
        assert "ningún cambio se aplicó" in answer.content
        assert all(call.tool_name == "get_coach_brief" for call in conversation.tool_calls)


def test_coverage_gates_nutrition_activity_and_goals_with_owner_isolation(app, user):
    with app.app_context():
        other = User(username="fictional-coach-neighbor", role="user")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.flush()
        today = date(2026, 10, 6)
        for days_back in range(6):
            for owner, offset, energy, steps in (
                (user, days_back, "1800", 5000),
                (user, days_back + 7, "2200", 8000),
                (other.id, days_back, "9000", 30000),
            ):
                day = today - timedelta(days=offset)
                db.session.add(DailyNutrition(user_id=owner, date=day, source="qa_fixture",
                                              calories=Decimal(energy), protein_g=Decimal("100")))
                db.session.add(DailyEnergy(user_id=owner, date=day, source="qa_fixture", steps=steps,
                                           active_calories=Decimal("250")))
        create_goal(user, {"goal_type": "daily_steps", "target_value": "7000", "unit": "step",
                           "period": "daily", "timezone": "UTC", "start_date": "2026-09-01"})
        db.session.commit()
        brief = CoachBriefService().build(db.session.get(User, user), today=today)
        types = {item["type"] for item in brief["week"]["signals"]}
        assert {"energy_change", "steps_change", "goal_gap"} <= types
        energy = next(item for item in brief["week"]["signals"] if item["type"] == "energy_change")
        assert energy["coverage"]["observed"] == 6
        assert energy["current"] == "1800.00" and energy["baseline"] == "2200.00"
        assert len(brief["week"]["top_priorities"]) <= 5
        assert "9000" not in str(brief)


def test_partial_nutrition_never_claims_lower_intake(app, user):
    with app.app_context():
        today = date(2026, 10, 6)
        for offset in (0, 1, 7, 8, 9, 10, 11, 12):
            db.session.add(DailyNutrition(user_id=user, date=today-timedelta(days=offset),
                                          source="qa_fixture", calories=Decimal("1200" if offset < 7 else "2400")))
        db.session.commit()
        brief = CoachBriefService().build(db.session.get(User, user), today=today)["week"]
        assert not any(item["type"] == "energy_change" for item in brief["signals"])
        assert any(item["metric"] == "energy_average" and item["coverage"]["state"] == "partial"
                   for item in brief["signals"])


def test_cross_domain_requires_matching_windows_and_nutrition_coverage(app, user):
    with app.app_context():
        _, _, sessions = strength_fixture(user, now=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
        for session in sessions[-2:]:
            for occurrence in list(session.exercises):
                if occurrence.name in {"QA Nuevo", "QA Sin vínculo"}:
                    db.session.delete(occurrence)
        for series in sessions[-1].exercises[0].sets:
            series.weight_kg = Decimal("100")
        today = date(2026, 10, 6)
        current_rows = []
        for offset in range(6):
            for age, value in ((offset, "1800"), (offset+7, "2300")):
                row = DailyNutrition(user_id=user, date=today-timedelta(days=age),
                                     source="qa_fixture", calories=Decimal(value))
                db.session.add(row)
                if age < 7:
                    current_rows.append(row)
        db.session.commit()
        account = db.session.get(User, user)
        brief = CoachBriefService().build(account, today=today)["week"]
        assert any(item["type"] == "training_nutrition_change" for item in brief["signals"])
        for row in current_rows[:4]:
            db.session.delete(row)
        db.session.commit()
        partial = CoachBriefService().build(account, today=today)["week"]
        assert not any(item["type"] == "training_nutrition_change" for item in partial["signals"])


@pytest.mark.parametrize("failure,code", [("timeout", "provider_timeout"),
                                          ("malformed", "invalid_provider_response")])
def test_provider_failure_keeps_deterministic_coach_available(app, client, user, failure, code):
    class FailedCoachProvider(FakeAIProvider):
        def respond(self, _request):
            if failure == "timeout":
                raise AIProviderError("provider_timeout", "Fallo ficticio", 504)
            return AIProviderResponse(content=None)

    with app.app_context():
        app.config.update(AI_ENABLED=True, AI_PROVIDER="fake", AI_MODEL="fake-health-v1",
                          AI_PROVIDER_INSTANCE=FailedCoachProvider(), AI_RATE_LIMIT_ENABLED=False)
        service = AIConversationService()
        conversation = service.create(user, title="Coach QA fallo ficticio")
        with pytest.raises(AIServiceError) as error:
            service.send_message(db.session.get(User, user), conversation.public_id,
                "Explica el brief", intent_spec=AIIntentSpec(AIIntent.WEEKLY_COACH, "all", period="7d"))
        assert error.value.code == code
        assert "resumen de Health Tracker sigue disponible" in error.value.safe_message
        conversation_id = conversation.public_id
    login(client)
    response = client.get(f"/ai/conversations/{conversation_id}?intent=weekly_coach&domain=all&period=7d")
    assert response.status_code == 200
    assert "Lectura del Coach" in response.text
    assert "Si la explicación AI falla" in response.text


@pytest.mark.parametrize("exercise_count", [5, 40])
def test_coach_reads_are_batched_not_one_query_per_exercise(app, user, exercise_count):
    with app.app_context():
        strength_fixture(user, count=4, exercise_count=exercise_count)
        db.session.remove()
        account = db.session.get(User, user)
        queries = []

        def count(*_args):
            queries.append(1)

        event.listen(db.engine, "before_cursor_execute", count)
        try:
            briefs = CoachBriefService().build(account)
        finally:
            event.remove(db.engine, "before_cursor_execute", count)
        assert briefs["today"]["top_priorities"] and briefs["week"]["top_priorities"]
        assert len(queries) <= 30


def test_coach_logs_ids_and_coverage_without_health_values(app, user, caplog):
    with app.app_context():
        strength_fixture(user)
        caplog.clear()
        with caplog.at_level("INFO"):
            CoachBriefService().build(db.session.get(User, user))
        assert "coach_brief period=week" in caplog.text
        assert "signal_ids=" in caplog.text and "coverage=" in caplog.text
        assert "QA Press banca" not in caplog.text
        assert "82.50" not in caplog.text
