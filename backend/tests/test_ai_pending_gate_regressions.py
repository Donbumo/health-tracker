"""Fictional QA regressions for pending-plan isolation and strict proposals."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging

import pytest

from app.extensions import db
from app.models import AIActionDraft, AIToolCall, NutritionItem, UserGoal, WeighIn
from app.services.ai.capabilities.types import AIIntent, AIIntentSpec
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import AIProvider
from app.services.ai.types import (
    AIProviderCapabilities,
    AIProviderPlanProposal,
    AIProviderPlanStepProposal,
    AIProviderResponse,
    AIProviderToolCall,
)
from tests.test_ai_operator_actions import (
    PlainPlanConversationProvider,
    PlanProvider,
    _account,
    _enable_ai,
    _goal,
)


def _pending_goal_after_body(app, user):
    """Prepare fictional two-step state with only the goal value missing."""
    _enable_ai(app, PlainPlanConversationProvider())
    account = _account(user)
    _goal(user, goal_type="daily_steps", target="9000")
    service = AIConversationService()
    conversation = service.create(user)
    service.send_message(
        account, conversation.public_id, "Registra mi peso y cambia mi meta de pasos"
    )
    _message, rows = service.send_message(
        account, conversation.public_id, "82.5 kg"
    )
    assert [row.provenance_json["step_status"] for row in rows] == [
        "ready", "needs_input"
    ]
    return account, service, conversation, rows


def _draft_snapshot(rows):
    return {
        row.public_id: (deepcopy(row.payload_json), deepcopy(row.provenance_json))
        for row in rows
    }


@pytest.mark.parametrize(
    "question",
    (
        "Analiza mis últimos 30 días",
        "¿Cuántos días registré durante los últimos 7 días?",
        "Explícame qué significa una meta de 10000 pasos",
    ),
)
def test_unrelated_numeric_question_does_not_complete_pending_slots(app, user, question):
    with app.app_context():
        account, service, conversation, rows = _pending_goal_after_body(app, user)
        original = _draft_snapshot(rows)

        _message, new_drafts = service.send_message(
            account, conversation.public_id, question
        )

        assert new_drafts == []
        assert _draft_snapshot(rows) == original
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(NutritionItem)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


@pytest.mark.parametrize("explicit_intent", (False, True))
def test_new_food_plan_does_not_fill_or_reuse_pending_goal_plan(app, user, explicit_intent):
    with app.app_context():
        account, service, conversation, rows = _pending_goal_after_body(app, user)
        original = _draft_snapshot(rows)
        pending_plan_id = rows[0].provenance_json["plan_id"]
        app.config["AI_PROVIDER_INSTANCE"] = PlanProvider(
            AIProviderPlanProposal(
                "record",
                "Comida QA ficticia para revisar",
                (
                    AIProviderPlanStepProposal(
                        "food_qa",
                        "nutrition.food.create",
                        {
                            "meal_type": "lunch",
                            "items": [{"name": "Pollo QA ficticio", "quantity": "200", "unit": "g"}],
                        },
                    ),
                ),
            )
        )
        spec = (
            AIIntentSpec(
                AIIntent.RECORD, "nutrition", (), "today", action="nutrition.food.create"
            )
            if explicit_intent else None
        )

        _message, new_drafts = service.send_message(
            account,
            conversation.public_id,
            "Registra mi comida: 200 g de pollo QA ficticio",
            intent_spec=spec,
        )

        assert len(new_drafts) == 1
        assert new_drafts[0].provenance_json["action_capability_id"] == "nutrition.food.create"
        assert new_drafts[0].provenance_json["plan_id"] != pending_plan_id
        assert _draft_snapshot(rows) == original
        assert db.session.execute(db.select(db.func.count(AIActionDraft.id))).scalar_one() == 3
        assert db.session.execute(db.select(NutritionItem)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


def test_goal_change_from_previous_value_preserves_destination(app, user):
    _enable_ai(
        app,
        PlanProvider(
            AIProviderPlanProposal(
                "correct",
                "Nueva meta QA ficticia para revisar",
                (
                    AIProviderPlanStepProposal(
                        "goal_qa", "goal.update",
                        {"goal_type": "daily_steps", "target_value": "10000", "unit": "step"},
                    ),
                ),
            )
        ),
    )
    with app.app_context():
        account = _account(user)
        _goal(user, goal_type="daily_steps", target="9000")
        service = AIConversationService()
        conversation = service.create(user)
        _message, drafts = service.send_message(
            account, conversation.public_id, "Cambia mi meta de pasos de 9000 a 10000"
        )

        assert len(drafts) == 1
        assert Decimal(str(drafts[0].payload_json["target_value"])) == Decimal("10000")
        assert drafts[0].provenance_json["step_status"] == "ready"
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


class ForbiddenPostReadToolProvider(AIProvider):
    name = "forbidden-post-read-qa"
    capabilities = AIProviderCapabilities(supports_tools=True)

    def __init__(self):
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        assert self.calls == 1, "A forbidden post-read tool must not cause another provider call"
        assert request.phase == "proposal"
        assert request.tools == ()
        assert any(result.name == "get_goals_summary" and result.ok for result in request.tool_results)
        return AIProviderResponse(
            tool_calls=(AIProviderToolCall("forbidden-qa", "get_nutrition_summary", {"preset": "7d"}),)
        )


def test_forbidden_provider_tool_after_required_read_fails_without_drafts(app, user):
    provider = ForbiddenPostReadToolProvider()
    _enable_ai(app, provider)
    with app.app_context():
        account = _account(user)
        _goal(user)
        service = AIConversationService()
        conversation = service.create(user)

        with pytest.raises(AIServiceError):
            service.send_message(account, conversation.public_id, "Propón cambios a mis metas")

        assert provider.calls == 1
        calls = db.session.execute(db.select(AIToolCall)).scalars().all()
        assert any(row.tool_name == "get_goals_summary" and row.status == "completed" for row in calls)
        assert not any(row.tool_name == "get_nutrition_summary" and row.status == "completed" for row in calls)
        assert db.session.execute(db.select(AIActionDraft)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


@pytest.mark.parametrize("malformation", ("unknown_field", "unknown_dependency"))
def test_malformed_provider_plan_is_not_hidden_by_server_slot_plan(app, user, malformation):
    body_arguments = {"unexpected_qa_field": "fixture"} if malformation == "unknown_field" else {}
    dependencies = ("missing_qa_step",) if malformation == "unknown_dependency" else ()
    _enable_ai(
        app,
        PlanProvider(
            AIProviderPlanProposal(
                "hybrid",
                "Plan QA malformado que debe rechazarse",
                (
                    AIProviderPlanStepProposal(
                        "body_qa", "body.measurement.create", body_arguments, dependencies
                    ),
                    AIProviderPlanStepProposal(
                        "goal_qa", "goal.update", {"goal_type": "daily_steps"}
                    ),
                ),
            )
        ),
    )
    with app.app_context():
        account = _account(user)
        _goal(user, goal_type="daily_steps", target="9000")
        service = AIConversationService()
        conversation = service.create(user)

        with pytest.raises(AIServiceError):
            service.send_message(
                account, conversation.public_id, "Registra mi peso y cambia mi meta de pasos"
            )

        assert db.session.execute(db.select(AIActionDraft)).scalars().all() == []
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


def test_selected_action_rejects_hybrid_plan_intent(app, user):
    _enable_ai(
        app,
        PlanProvider(
            AIProviderPlanProposal(
                "hybrid",
                "Intención QA no compatible",
                (
                    AIProviderPlanStepProposal(
                        "goal_qa",
                        "goal.update",
                        {"goal_type": "daily_steps", "target_value": "10000", "unit": "step"},
                    ),
                ),
            )
        ),
    )
    with app.app_context():
        account = _account(user)
        _goal(user, goal_type="daily_steps", target="9000")
        service = AIConversationService()
        conversation = service.create(user)
        with pytest.raises(AIServiceError) as rejected:
            service.send_message(
                account,
                conversation.public_id,
                "Cambia mi meta de pasos a 10000",
                intent_spec=AIIntentSpec(
                    AIIntent.CORRECT,
                    "goals",
                    (),
                    "today",
                    action="goal.update",
                ),
            )
        assert rejected.value.code == "invalid_plan_intent"
        assert db.session.execute(db.select(AIActionDraft)).scalars().all() == []


@pytest.mark.parametrize("marked_expired", (False, True))
def test_expired_pending_plan_cannot_be_resurrected_by_slot_reply(app, user, marked_expired):
    with app.app_context():
        account, service, conversation, rows = _pending_goal_after_body(app, user)
        rows[1].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if marked_expired:
            rows[1].status = "expired"
        db.session.commit()
        original = _draft_snapshot(rows)
        old_expiry = rows[1].expires_at
        old_status = rows[1].status

        _message, new_drafts = service.send_message(
            account, conversation.public_id, "10000"
        )

        assert new_drafts == []
        assert _draft_snapshot(rows) == original
        assert rows[1].expires_at == old_expiry
        assert rows[1].status == old_status
        assert db.session.execute(db.select(db.func.count(AIActionDraft.id))).scalar_one() == 2
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


def test_slot_completion_preserves_applied_step_identity_and_dependencies(app, user):
    _enable_ai(
        app,
        PlanProvider(
            AIProviderPlanProposal(
                "hybrid",
                "Plan QA ficticio con dependencia",
                (
                    AIProviderPlanStepProposal(
                        "body_qa", "body.measurement.create",
                        {"weight": "82.5", "unit": "kg"},
                    ),
                    AIProviderPlanStepProposal(
                        "goal_qa", "goal.update",
                        {"goal_type": "daily_steps", "unit": "step"},
                        ("body_qa",),
                    ),
                ),
            )
        ),
    )
    with app.app_context():
        account = _account(user)
        goal = _goal(user, goal_type="daily_steps", target="9000")
        service = AIConversationService()
        conversation = service.create(user)
        _message, initial = service.send_message(
            account, conversation.public_id,
            "Registra mi peso de 82.5 kg y actualiza mi meta de pasos",
        )
        assert [row.provenance_json["step_status"] for row in initial] == [
            "ready", "needs_input"
        ]
        original_ids = [row.public_id for row in initial]
        original_plan_id = initial[0].provenance_json["plan_id"]
        service.confirm_draft(account, initial[0].public_id)
        applied_snapshot = _draft_snapshot(initial[:1])
        applied_at = initial[0].applied_at
        resources = list(initial[0].applied_resource_public_ids_json)
        assert db.session.execute(db.select(db.func.count(WeighIn.id))).scalar_one() == 1
        app.config["AI_PROVIDER_INSTANCE"] = PlainPlanConversationProvider()

        _message, completed = service.send_message(
            account, conversation.public_id, "10000"
        )

        assert [row.public_id for row in completed] == original_ids
        assert {row.provenance_json["plan_id"] for row in completed} == {original_plan_id}
        assert [row.provenance_json["step_index"] for row in completed] == [1, 2]
        assert [row.provenance_json["step_id"] for row in completed] == ["body_qa", "goal_qa"]
        assert [row.provenance_json["dependencies"] for row in completed] == [[], ["body_qa"]]
        assert [row.provenance_json["step_status"] for row in completed] == ["applied", "ready"]
        assert _draft_snapshot(completed[:1]) == applied_snapshot
        assert completed[0].applied_at == applied_at
        assert completed[0].applied_resource_public_ids_json == resources
        assert db.session.execute(db.select(db.func.count(AIActionDraft.id))).scalar_one() == 2
        assert db.session.execute(db.select(db.func.count(WeighIn.id))).scalar_one() == 1
        assert db.session.get(UserGoal, goal.id).revision == 1

        service.confirm_draft(account, completed[1].public_id)
        service.confirm_draft(account, completed[0].public_id)
        service.confirm_draft(account, completed[1].public_id)
        assert db.session.get(UserGoal, goal.id).revision == 2
        assert db.session.execute(db.select(db.func.count(WeighIn.id))).scalar_one() == 1
        assert db.session.execute(db.select(db.func.count(AIActionDraft.id))).scalar_one() == 2


def test_incompatible_unit_in_pending_goal_reply_is_rejected_without_mutation(app, user):
    with app.app_context():
        account, service, conversation, rows = _pending_goal_after_body(app, user)
        original = _draft_snapshot(rows)

        with pytest.raises(AIServiceError) as rejected:
            service.send_message(account, conversation.public_id, "10000 g")

        assert rejected.value.code == "invalid_goal_contract"
        assert _draft_snapshot(rows) == original
        assert db.session.execute(db.select(db.func.count(AIActionDraft.id))).scalar_one() == 2
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(UserGoal.revision)).scalar_one() == 1


def test_validation_log_replaces_arbitrary_goal_metadata_with_unknown(app, user, caplog):
    unknown_values = {
        "goal_type": "fictional_92746",
        "metric_id": "fictional_82635",
        "unit": "fictional_72524",
    }
    _enable_ai(
        app,
        PlanProvider(
            AIProviderPlanProposal(
                "correct", "Metadatos QA no permitidos",
                (
                    AIProviderPlanStepProposal(
                        "goal_qa", "goal.update",
                        {**unknown_values, "target_value": "10000"},
                    ),
                ),
            )
        ),
    )
    with app.app_context(), caplog.at_level(logging.WARNING):
        account = _account(user)
        service = AIConversationService()
        conversation = service.create(user)
        with pytest.raises(AIServiceError):
            service.send_message(account, conversation.public_id, "Prepara un ajuste QA ficticio")

        audit = next(
            record.getMessage() for record in caplog.records
            if "ai_plan_validation_rejected" in record.getMessage()
        )
        assert "goal_type=unknown" in audit
        assert "metric_id=unknown" in audit
        assert "unit_id=unknown" in audit
        assert all(value not in caplog.text for value in unknown_values.values())
        assert "10000" not in audit
        assert db.session.execute(db.select(AIActionDraft)).scalars().all() == []
