from __future__ import annotations

from datetime import date
import json
import logging
import os
from pathlib import Path
import time
from urllib.parse import parse_qs, urlencode, urlparse
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    AIActionDraft,
    AIToolCall,
    NutritionItem,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    User,
    UserGoal,
    WeighIn,
)
from app.services.ai.capabilities.composer import AdaptiveTemplateComposer
from app.services.ai.capabilities.context import (
    issue_action_context_token,
    load_action_context_token,
)
from app.services.ai.capabilities.domains import load_manifests
from app.services.ai.capabilities.domains.goal_actions import GOAL_UPDATE
from app.services.ai.capabilities.domains.training_actions import TRAINING_CREATE
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionApplyResult,
    ActionCapability,
    AIIntent,
    AIIntentSpec,
    AIPlanStepStatus,
    CapabilityError,
    DataAvailability,
)
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import AIProvider, AIProviderError, OpenAIResponsesProvider
from app.services.ai.tools import AIToolRegistry
from app.services.ai.types import (
    AIProviderPlanProposal,
    AIProviderPlanStepProposal,
    AIProviderResponse,
)
from app.services.engagement import create_goal
from tests.conftest import login


def _enable_ai(app, provider=None):
    app.config.update(
        AI_ENABLED=True,
        AI_PROVIDER="fake",
        AI_MODEL="fake-health-v1",
        AI_PROVIDER_INSTANCE=provider,
        AI_RATE_LIMIT_ENABLED=False,
        AI_TODAY_OVERRIDE=date(2026, 9, 6),
    )


def _account(user_id: int) -> User:
    return db.session.get(User, user_id)


def _goal(user_id: int, *, goal_type="nutrition_protein", target="140") -> UserGoal:
    row = create_goal(
        user_id,
        {
            "goal_type": goal_type,
            "target_value": target,
            "unit": "g" if goal_type == "nutrition_protein" else "step",
            "period": "daily",
            "timezone": "UTC",
            "start_date": "2026-09-01",
        },
    )
    db.session.commit()
    return row


def _training_plan(user_id: int) -> TrainingPlan:
    content = {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "name": "Rutina Operator QA ficticia",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Fuerza QA ficticia",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Sentadilla QA ficticia",
                                    "sets": [
                                        {
                                            "set_number": 1,
                                            "reps": 5,
                                            "rest_seconds": 90,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }
    plan = TrainingPlan(
        user_id=user_id,
        name="Rutina Operator QA ficticia",
        active_version_number=1,
    )
    db.session.add(plan)
    db.session.flush()
    db.session.add(
        TrainingPlanVersion(
            user_id=user_id,
            training_plan=plan,
            version_number=1,
            created_by_user_id=user_id,
            schema_version="1.0",
            sha256="9" * 64,
            content=content,
        )
    )
    db.session.commit()
    return plan


def _completed_exercises(weight=50, reps=5):
    return [
        {
            "exercise_order": 1,
            "planned_exercise_order": 1,
            "name": "Sentadilla QA ficticia",
            "sets": [
                {
                    "set_number": 1,
                    "planned_set_number": 1,
                    "weight_kg": weight,
                    "reps": reps,
                    "rir": 2,
                    "rpe": 8,
                    "rest_seconds": 90,
                }
            ],
        }
    ]


class PlanProvider(AIProvider):
    name = "operator-plan-test"

    def __init__(self, proposal: AIProviderPlanProposal):
        self.proposal = proposal
        self.calls = 0

    def respond(self, _request):
        self.calls += 1
        return AIProviderResponse(
            content="Plan QA preparado; aún no se aplicó.", plans=(self.proposal,)
        )


class FailOnCallProvider(AIProvider):
    name = "must-not-be-called"

    def respond(self, _request):
        raise AssertionError("A local draft edit must not call the provider")


def test_action_contract_and_plan_resolver_are_strict_and_server_owned(app, user):
    with app.app_context():
        account = _account(user)
        registry = AICapabilityRegistry()
        incomplete = registry.action("nutrition.food.create").create_draft(account, {})
        assert incomplete.status == AIPlanStepStatus.NEEDS_INPUT
        assert set(incomplete.arguments["missing_fields"]) == {"meal_type", "items"}

        with pytest.raises(CapabilityError) as unsupported:
            registry.action("nutrition.food.create").create_draft(
                account, {"meal_type": "breakfast", "items": [], "service": "db.drop_all"}
            )
        assert unsupported.value.code == "unsupported_action_field"

        with pytest.raises(CapabilityError) as unknown:
            registry.resolve_action_proposal(
                account,
                AIProviderPlanProposal(
                    "record",
                    "Plan inválido QA",
                    (AIProviderPlanStepProposal("step_1", "unknown.write", {}),),
                ),
            )
        assert unknown.value.code == "unknown_action"

        with pytest.raises(CapabilityError) as cyclic:
            registry.resolve_action_proposal(
                account,
                AIProviderPlanProposal(
                    "record",
                    "Ciclo QA",
                    (
                        AIProviderPlanStepProposal(
                            "step_a", "body.measurement.create", {"weight": 70, "unit": "kg"}, ("step_b",)
                        ),
                        AIProviderPlanStepProposal(
                            "step_b", "nutrition.food.create", {"meal_type": "other", "items": [{"name": "QA"}]}, ("step_a",)
                        ),
                    ),
                ),
            )
        assert cyclic.value.code == "invalid_plan_dependencies"

        plan = registry.resolve_action_proposal(
            account,
            AIProviderPlanProposal(
                "record",
                "Plan válido QA",
                (
                    AIProviderPlanStepProposal(
                        "step_1", "body.measurement.create", {"weight": 70, "unit": "kg"}
                    ),
                ),
            ),
        )
        assert str(uuid.UUID(plan.plan_id)) == plan.plan_id
        assert plan.steps[0].domain == "body"
        assert plan.steps[0].entity == "body_measurement"
        assert plan.steps[0].operation == "create"
        assert plan.steps[0].status == AIPlanStepStatus.READY

        goal = _goal(user, goal_type="daily_steps", target="9000")
        update = GOAL_UPDATE.create_draft(
            account,
            {"goal_type": "daily_steps", "target_value": "10000", "unit": "pasos"},
        )
        assert update.status == AIPlanStepStatus.READY
        assert update.arguments["unit"] == "step"
        assert update.context["public_id"] == goal.public_id
        with pytest.raises(CapabilityError) as incompatible_unit:
            GOAL_UPDATE.create_draft(
                account,
                {"goal_type": "daily_steps", "target_value": "10000", "unit": "g"},
            )
        assert incompatible_unit.value.code == "invalid_goal_contract"


def test_natural_multi_action_plan_has_zero_writes_then_supports_partial_workflow(
    app, user, caplog
):
    _enable_ai(app)
    with app.app_context(), caplog.at_level(logging.INFO):
        account = _account(user)
        goal = _goal(user)
        original_revision = goal.revision
        conversation = AIConversationService().create(user)
        message, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            (
                "Hoy pesé 82.5 kg, este desayuno tuvo 520 kcal y "
                "cambia mi meta de proteína a 160 g"
            ),
        )

        assert message.role == "assistant"
        assert [
            (row.provenance_json or {}).get("action_capability_id") for row in drafts
        ] == [
            "body.measurement.create",
            "nutrition.food.create",
            "goal.update",
        ]
        assert len({row.provenance_json["plan_id"] for row in drafts}) == 1
        assert all(row.status == "pending_confirmation" for row in drafts)
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(NutritionItem)).scalars().all() == []
        assert db.session.get(UserGoal, goal.id).revision == original_revision

        plan_logs = [record.getMessage() for record in caplog.records if "ai_plan_prepared" in record.getMessage()]
        assert plan_logs
        assert all(value not in " ".join(plan_logs) for value in ("82.5", "520", "160"))

        service = AIConversationService()
        body, food, goal_draft = drafts
        applied = service.confirm_draft(account, body.public_id)
        assert applied.status == "applied"
        rejected = service.reject_draft(user, food.public_id)
        assert rejected.status == "rejected"

        app.config["AI_PROVIDER_INSTANCE"] = FailOnCallProvider()
        edited = service.edit_draft(account, goal_draft.public_id, {"target_value": "150"})
        assert edited.payload_json["target_value"] == "150"
        assert edited.provenance_json["edited_locally"] is True
        summary = service.confirm_plan(account, edited.provenance_json["plan_id"])
        assert summary["counts"] == {
            "pending_confirmation": 0,
            "applied": 2,
            "rejected": 1,
            "failed": 0,
            "expired": 0,
        }
        assert service.confirm_draft(account, body.public_id).public_id == body.public_id
        assert db.session.execute(db.select(WeighIn)).scalars().all().__len__() == 1
        assert db.session.execute(db.select(NutritionItem)).scalars().all() == []
        updated_goal = db.session.get(UserGoal, goal.id)
        assert str(updated_goal.target_value) == "150.000"
        assert updated_goal.revision == original_revision + 1
        assert edited.provenance_json["write_provenance"] == "ai_assisted_user_confirmed"


def test_goal_create_is_confirmed_and_reconfirmation_is_idempotent(app, user):
    _enable_ai(app)
    with app.app_context():
        account = _account(user)
        conversation = AIConversationService().create(user)
        _message, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            "Crea una nueva meta de pasos de 10000",
        )
        assert len(drafts) == 1
        assert drafts[0].provenance_json["action_capability_id"] == "goal.create"
        assert db.session.execute(db.select(UserGoal)).scalars().all() == []
        service = AIConversationService()
        first = service.confirm_draft(account, drafts[0].public_id)
        second = service.confirm_draft(account, drafts[0].public_id)
        assert first.applied_resource_public_ids_json == second.applied_resource_public_ids_json
        goals = db.session.execute(db.select(UserGoal)).scalars().all()
        assert len(goals) == 1
        assert goals[0].goal_type == "daily_steps"
        assert str(goals[0].target_value) == "10000.000"


def test_training_create_and_correct_use_real_plan_bound_services(app, user):
    with app.app_context():
        account = _account(user)
        _training_plan(user)
        create_proposal = AIProviderPlanProposal(
            "record",
            "Entrenamiento QA",
            (
                AIProviderPlanStepProposal(
                    "training_create",
                    "training.session.create",
                    {
                        "plan_name": "Rutina Operator QA ficticia",
                        "week_number": 1,
                        "day_number": 1,
                        "workout_name": "Fuerza QA ficticia",
                        "performed_at": "2026-09-06T08:00:00+00:00",
                        "duration_seconds": 1800,
                        "exercises": _completed_exercises(),
                    },
                ),
            ),
        )
        _enable_ai(app, PlanProvider(create_proposal))
        conversation = AIConversationService().create(user)
        _message, drafts = AIConversationService().send_message(
            account, conversation.public_id, "Registra este entrenamiento QA ficticio"
        )
        assert drafts[0].provenance_json["step_status"] == "ready"
        assert db.session.execute(db.select(TrainingSession)).scalars().all() == []
        created = AIConversationService().confirm_draft(account, drafts[0].public_id)
        assert created.status == "applied"
        session = db.session.execute(db.select(TrainingSession)).scalar_one()
        assert session.notes is None

        correction_provider = PlanProvider(
            AIProviderPlanProposal(
                "correct",
                "Corrección QA",
                (
                    AIProviderPlanStepProposal(
                        "training_correct",
                        "training.session.correct",
                        {"notes": "Nota corregida QA ficticia"},
                    ),
                ),
            )
        )
        app.config["AI_PROVIDER_INSTANCE"] = correction_provider
        _message, correction_drafts = AIConversationService().send_message(
            account, conversation.public_id, "Corrige las notas del entrenamiento"
        )
        correction = correction_drafts[0]
        assert correction.provenance_json["preview"]["original"]["exercises"]
        assert correction.payload_json["exercises"] == _completed_exercises()
        applied = AIConversationService().confirm_draft(account, correction.public_id)
        assert applied.status == "applied"
        updated = db.session.get(TrainingSession, session.id)
        assert updated.notes == "Nota corregida QA ficticia"
        assert updated.revision == 2


def test_training_without_a_real_plan_day_stays_needs_input(app, user):
    with app.app_context():
        draft = TRAINING_CREATE.create_draft(
            _account(user),
            {
                "performed_at": "2026-09-06T08:00:00+00:00",
                "exercises": _completed_exercises(),
            },
        )
        assert draft.status == AIPlanStepStatus.NEEDS_INPUT
        assert draft.context["needs_input"] is True
        assert {"plan_name", "week_number", "day_number"} <= set(
            draft.arguments["missing_fields"]
        )


def test_proposal_mode_and_conversation_continuation_re_read_current_goals(app, user):
    _enable_ai(app)
    with app.app_context():
        account = _account(user)
        goal = _goal(user, target="145")
        conversation = AIConversationService().create(user)
        first_message, first_drafts = AIConversationService().send_message(
            account, conversation.public_id, "Analiza mi semana"
        )
        assert first_message.role == "assistant"
        assert first_drafts == []

        second_message, drafts = AIConversationService().send_message(
            account, conversation.public_id, "Entonces ajusta mis metas"
        )
        assert second_message.content.startswith("OBSERVACIONES")
        assert "CAMBIOS PROPUESTOS" in second_message.content
        assert len(drafts) == 1
        assert drafts[0].status == "pending_confirmation"
        assert drafts[0].provenance_json["plan_intent"] == "propose_changes"
        tool_calls = db.session.execute(
            db.select(AIToolCall).where(AIToolCall.user_id == user)
        ).scalars().all()
        assert tool_calls[-1].tool_name == "get_goals_summary"
        assert db.session.get(UserGoal, goal.id).revision == 1
        assert str(db.session.get(UserGoal, goal.id).target_value) == "145.000"


def test_context_token_is_valid_owner_bound_tamper_proof_and_expiring(
    app, client, user, monkeypatch
):
    with app.app_context():
        goal = _goal(user)
        token = issue_action_context_token(
            user_id=user,
            action_capability_id="goal.update",
            domain="goals",
            resource_type="user_goal",
            resource_public_id=goal.public_id,
        )
        context = load_action_context_token(token, user_id=user)
        assert context.resource_public_id == goal.public_id
        assert context.action_capability_id == "goal.update"

        route = "/ai?" + urlencode(
            {
                "intent": "correct",
                "domain": "goals",
                "action": "goal.update",
                "period": "today",
                "action_context": token,
            }
        )
        query = parse_qs(urlparse(route).query)
        assert set(query) == {"intent", "domain", "action", "period", "action_context"}
        assert "140" not in route
        login(client)
        assert client.get(route).status_code == 200
        assert client.get(
            "/ai?intent=record&domain=body&action=arbitrary.service&period=today"
        ).status_code == 409

        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(CapabilityError) as invalid_signature:
            load_action_context_token(tampered, user_id=user)
        assert invalid_signature.value.code == "invalid_action_context"

        other = User(username="operator-other-user", role="user", timezone="UTC")
        other.set_password("fictional-other-password")
        db.session.add(other)
        db.session.commit()
        other_goal = _goal(other.id)
        other_token = issue_action_context_token(
            user_id=other.id,
            action_capability_id="goal.update",
            domain="goals",
            resource_type="user_goal",
            resource_public_id=other_goal.public_id,
        )
        with pytest.raises(CapabilityError) as invalid_token:
            load_action_context_token(other_token, user_id=user)
        assert invalid_token.value.code == "invalid_action_context"

        with pytest.raises(CapabilityError) as cross_user:
            GOAL_UPDATE.create_draft(
                _account(user),
                {"target_value": "150"},
                resource_context={
                    "resource_type": "user_goal",
                    "resource_public_id": other_goal.public_id,
                },
            )
        assert cross_user.value.code == "action_context_not_found"

        app.config["AI_ACTION_CONTEXT_MAX_AGE_SECONDS"] = 60
        issued_at = time.time()
        monkeypatch.setattr("itsdangerous.timed.time.time", lambda: issued_at + 61)
        with pytest.raises(CapabilityError) as expired:
            load_action_context_token(token, user_id=user)
        assert expired.value.code == "invalid_action_context"


def test_plan_dependency_partial_failure_and_safe_retry_do_not_duplicate_food(app, user):
    state = {"fail": True}

    def flaky_apply(_user, _draft, _payload, _context, _now):
        if state["fail"]:
            raise CapabilityError("qa_transient", "Fallo transitorio QA.", 409)
        return ActionApplyResult("qa_resource", ("11111111-1111-4111-8111-111111111111",))

    qa_action = ActionCapability(
        action_id="qa.marker.create",
        domain="qa",
        entity="qa_marker",
        operation="create",
        label="Marcador QA",
        description="Acción ficticia para probar fallos parciales.",
        supported_fields=("label",),
        required_fields=("label",),
        optional_fields=(),
        input_schema={
            "type": "object",
            "properties": {"label": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        },
        apply_handler=flaky_apply,
    )
    qa_manifest = AICapabilityManifest(
        domain_id="qa",
        label="QA",
        description="Dominio ficticio de pruebas.",
        entities=("qa_marker",),
        metrics=(),
        read_capabilities=(),
        action_capabilities=(qa_action,),
    )
    registry = AICapabilityRegistry(
        manifests=(*load_manifests(), qa_manifest), tool_registry=AIToolRegistry()
    )
    proposal = AIProviderPlanProposal(
        "hybrid",
        "Plan de fallo parcial QA",
        (
            AIProviderPlanStepProposal(
                "marker",
                "qa.marker.create",
                {"label": "marcador ficticio"},
                ("food",),
            ),
            AIProviderPlanStepProposal(
                "food",
                "nutrition.food.create",
                {"meal_type": "other", "items": [{"name": "Alimento QA ficticio"}]},
            ),
        ),
    )
    _enable_ai(app, PlanProvider(proposal))
    with app.app_context():
        account = _account(user)
        service = AIConversationService(capability_registry=registry)
        conversation = service.create(user)
        _message, drafts = service.send_message(
            account, conversation.public_id, "Ejecuta plan QA ficticio"
        )
        plan_id = drafts[0].provenance_json["plan_id"]
        summary = service.confirm_plan(account, plan_id)
        assert summary["counts"]["applied"] == 1
        assert summary["counts"]["failed"] == 1
        assert db.session.execute(db.select(NutritionItem)).scalars().all().__len__() == 1

        state["fail"] = False
        retried = service.retry_plan(account, plan_id)
        assert retried["counts"]["applied"] == 2
        assert retried["counts"]["failed"] == 0
        assert db.session.execute(db.select(NutritionItem)).scalars().all().__len__() == 1


def test_fake_sleep_action_is_discovered_resolved_previewed_and_persisted(app, user):
    calls = {"apply": 0}

    def apply_sleep(_user, _draft, _payload, _context, _now):
        calls["apply"] += 1
        return ActionApplyResult("sleep_entry", ("22222222-2222-4222-8222-222222222222",))

    sleep_action = ActionCapability(
        action_id="sleep.log",
        domain="sleep",
        entity="sleep_entry",
        operation="create",
        label="Registrar sueño",
        description="Fixture ficticia, no implementa Sleep real.",
        supported_fields=("duration", "quality"),
        required_fields=("duration", "quality"),
        optional_fields=(),
        input_schema={
            "type": "object",
            "properties": {
                "duration": {"type": "number", "minimum": 0, "maximum": 24},
                "quality": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "additionalProperties": False,
        },
        apply_handler=apply_sleep,
    )
    sleep_manifest = AICapabilityManifest(
        domain_id="sleep",
        label="Sueño QA",
        description="Sólo fixture de extensibilidad.",
        entities=("sleep_entry",),
        metrics=(),
        read_capabilities=(),
        action_capabilities=(sleep_action,),
    )
    registry = AICapabilityRegistry(
        manifests=(sleep_manifest,), tool_registry=AIToolRegistry()
    )
    with app.app_context():
        account = _account(user)
        experiences = AdaptiveTemplateComposer(registry).experiences(
            availability={"sleep": DataAvailability("sleep", 0, "no_data")}
        )
        discovered = next(item for item in experiences if item.spec.action == "sleep.log")
        assert discovered.spec == AIIntentSpec(
            AIIntent.RECORD, "sleep", period="today", action="sleep.log"
        )
        resolved = registry.resolve(discovered.spec)
        assert resolved.action is sleep_action

        provider = PlanProvider(
            AIProviderPlanProposal(
                "record",
                "Sueño QA",
                (
                    AIProviderPlanStepProposal(
                        "sleep_1", "sleep.log", {"duration": 7.5, "quality": 4}
                    ),
                ),
            )
        )
        _enable_ai(app, provider)
        service = AIConversationService(capability_registry=registry)
        conversation = service.create(user)
        _message, drafts = service.send_message(
            account, conversation.public_id, "Registra sueño QA ficticio"
        )
        assert len(drafts) == 1
        assert drafts[0].draft_type == "capability_action"
        assert drafts[0].status == "pending_confirmation"
        assert drafts[0].provenance_json["preview"]["fields"]
        assert drafts[0].provenance_json["step_status"] == "ready"
        assert sleep_action.confirmation_required is True
        assert calls["apply"] == 0


def test_plan_parser_and_web_routes_reject_malformed_or_unconfirmed_writes(
    app, client, user
):
    with pytest.raises(AIProviderError) as malformed:
        OpenAIResponsesProvider._parse_document(
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "propose_action_plan",
                        "call_id": "qa-call",
                        "arguments": json.dumps(
                            {
                                "intent": "record",
                                "summary": "QA",
                                "steps": [],
                                "service": "arbitrary",
                            }
                        ),
                    }
                ]
            }
        )
    assert malformed.value.code == "provider_malformed_action_plan"

    _enable_ai(app)
    with app.app_context():
        account = _account(user)
        conversation = AIConversationService().create(user)
        _message, drafts = AIConversationService().send_message(
            account, conversation.public_id, "Peso 73.2 kg"
        )
        draft_id = drafts[0].public_id
    login(client)
    app.config["WTF_CSRF_ENABLED"] = True
    denied = client.post(f"/ai/drafts/{draft_id}/confirm", data={"weight": "73.2", "unit": "kg"})
    assert denied.status_code == 400
    with app.app_context():
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []
        assert db.session.execute(db.select(AIActionDraft)).scalar_one().status == "pending_confirmation"


@pytest.mark.skipif(
    not Path("/.dockerenv").exists() and os.getenv("AI_MARIADB_QA") != "1",
    reason="MariaDB Operator integration runs only in Docker",
)
def test_mariadb_operator_multistep_goal_training_and_partial_retry(app, tmp_path):
    mariadb_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "operator-mariadb-secret-key-long-enough",
            "API_TOKEN_SIGNING_KEY": "operator-mariadb-signing-key-long-enough",
            "DATA_ROOT": tmp_path / "operator-mariadb",
            "UPLOAD_ROOT": tmp_path / "operator-mariadb" / "raw",
            "GENERATED_UPLOAD_ROOT": tmp_path / "operator-mariadb" / "generated",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "API_RATE_LIMIT_ENABLED": False,
            "AI_ENABLED": True,
            "AI_PROVIDER": "fake",
            "AI_MODEL": "fake-health-v1",
            "AI_TODAY_OVERRIDE": date(2026, 9, 6),
        }
    )
    state = {"fail": True}

    def flaky_apply(_user, _draft, _payload, _context, _now):
        if state["fail"]:
            raise CapabilityError("qa_transient", "Fallo transitorio QA.", 409)
        return ActionApplyResult(
            "qa_resource", ("33333333-3333-4333-8333-333333333333",)
        )

    username = f"operator-mariadb-{uuid.uuid4().hex}"
    with mariadb_app.app_context():
        account = User(username=username, role="user", timezone="UTC")
        account.set_password("fictional-operator-mariadb-password")
        db.session.add(account)
        db.session.commit()
        account_id = account.id
        try:
            goal = _goal(account_id, target="140")
            _training_plan(account_id)
            multi_provider = PlanProvider(
                AIProviderPlanProposal(
                    "hybrid",
                    "Plan multi-dominio QA ficticio",
                    (
                        AIProviderPlanStepProposal(
                            "body",
                            "body.measurement.create",
                            {"weight": 79.4, "unit": "kg"},
                        ),
                        AIProviderPlanStepProposal(
                            "goal",
                            "goal.update",
                            {"goal_type": "nutrition_protein", "target_value": "150"},
                        ),
                    ),
                )
            )
            mariadb_app.config["AI_PROVIDER_INSTANCE"] = multi_provider
            service = AIConversationService()
            conversation = service.create(account_id)
            _message, drafts = service.send_message(
                account, conversation.public_id, "Prepara plan multi-dominio QA ficticio"
            )
            assert len(drafts) == 2
            assert db.session.execute(
                db.select(WeighIn).where(WeighIn.user_id == account_id)
            ).scalars().all() == []
            assert db.session.get(UserGoal, goal.id).revision == 1

            plan_id = drafts[0].provenance_json["plan_id"]
            summary = service.confirm_plan(account, plan_id)
            repeated = service.confirm_plan(account, plan_id)
            assert summary["counts"]["applied"] == repeated["counts"]["applied"] == 2
            assert len(
                db.session.execute(
                    db.select(WeighIn).where(WeighIn.user_id == account_id)
                ).scalars().all()
            ) == 1
            assert str(db.session.get(UserGoal, goal.id).target_value) == "150.000"
            assert db.session.get(UserGoal, goal.id).revision == 2

            mariadb_app.config["AI_PROVIDER_INSTANCE"] = PlanProvider(
                AIProviderPlanProposal(
                    "record",
                    "Entrenamiento QA ficticio",
                    (
                        AIProviderPlanStepProposal(
                            "training",
                            "training.session.create",
                            {
                                "plan_name": "Rutina Operator QA ficticia",
                                "week_number": 1,
                                "day_number": 1,
                                "workout_name": "Fuerza QA ficticia",
                                "performed_at": "2026-09-06T08:00:00+00:00",
                                "duration_seconds": 1800,
                                "exercises": _completed_exercises(),
                            },
                        ),
                    ),
                )
            )
            _message, training_drafts = service.send_message(
                account, conversation.public_id, "Registra entrenamiento QA ficticio"
            )
            service.confirm_draft(account, training_drafts[0].public_id)
            assert len(
                db.session.execute(
                    db.select(TrainingSession).where(
                        TrainingSession.user_id == account_id
                    )
                ).scalars().all()
            ) == 1

            qa_action = ActionCapability(
                action_id="qa.mariadb_marker.create",
                domain="qa_mariadb",
                entity="qa_marker",
                operation="create",
                label="Marcador MariaDB QA",
                description="Acción ficticia para fallo parcial en MariaDB.",
                supported_fields=("label",),
                required_fields=("label",),
                optional_fields=(),
                input_schema={
                    "type": "object",
                    "properties": {"label": {"type": "string", "minLength": 1}},
                    "additionalProperties": False,
                },
                apply_handler=flaky_apply,
            )
            qa_manifest = AICapabilityManifest(
                domain_id="qa_mariadb",
                label="QA MariaDB",
                description="Dominio ficticio para integración MariaDB.",
                entities=("qa_marker",),
                metrics=(),
                read_capabilities=(),
                action_capabilities=(qa_action,),
            )
            registry = AICapabilityRegistry(
                manifests=(*load_manifests(), qa_manifest),
                tool_registry=AIToolRegistry(),
            )
            mariadb_app.config["AI_PROVIDER_INSTANCE"] = PlanProvider(
                AIProviderPlanProposal(
                    "hybrid",
                    "Fallo parcial MariaDB QA",
                    (
                        AIProviderPlanStepProposal(
                            "marker",
                            "qa.mariadb_marker.create",
                            {"label": "marcador ficticio"},
                            ("food",),
                        ),
                        AIProviderPlanStepProposal(
                            "food",
                            "nutrition.food.create",
                            {
                                "meal_type": "other",
                                "items": [{"name": "Alimento MariaDB QA ficticio"}],
                            },
                        ),
                    ),
                )
            )
            partial_service = AIConversationService(capability_registry=registry)
            _message, partial_drafts = partial_service.send_message(
                account, conversation.public_id, "Ejecuta fallo parcial MariaDB QA"
            )
            partial_plan_id = partial_drafts[0].provenance_json["plan_id"]
            partial = partial_service.confirm_plan(account, partial_plan_id)
            assert partial["counts"]["applied"] == 1
            assert partial["counts"]["failed"] == 1
            state["fail"] = False
            retried = partial_service.retry_plan(account, partial_plan_id)
            assert retried["counts"]["applied"] == 2
            assert retried["counts"]["failed"] == 0
            assert len(
                db.session.execute(
                    db.select(NutritionItem).where(NutritionItem.user_id == account_id)
                ).scalars().all()
            ) == 1
        finally:
            db.session.execute(db.delete(User).where(User.id == account_id))
            db.session.commit()
