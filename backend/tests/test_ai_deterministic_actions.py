"""Fictional QA: common actions must succeed with a provider that explodes."""
from dataclasses import replace
from decimal import Decimal
import logging
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import text as sql_text

from app.extensions import db
from app import create_app
from app.models import AIActionDraft, AIConversation, AIMessage, AIToolCall, NutritionItem, User, UserGoal, WeighIn
from app.services.ai.capabilities.domains import load_manifests
from app.services.ai.capabilities.interpreter import DeterministicActionInterpreter
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import (
    AICapabilityManifest, ActionCapability, ActionLanguage, ActionNumericSlot,
    ActionApplyResult, AIIntent, AIIntentSpec,
)
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import FakeAIProvider
from tests.test_ai_operator_actions import _account, _enable_ai, _goal


class ExplodingProvider(FakeAIProvider):
    def __init__(self):
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        raise AssertionError("Deterministic actions must not call the provider")


@pytest.fixture
def offline(app):
    provider = ExplodingProvider()
    _enable_ai(app, provider)
    return provider


def send(user, text, service=None, conversation=None):
    service = service or AIConversationService()
    conversation = conversation or service.create(user)
    return service.send_message(_account(user), conversation.public_id, text)


@pytest.mark.parametrize("text", ["Hoy pesé 82.5 kg", "Registra mi peso en 82.5", "Mi peso hoy fue 82.5 kg"])
def test_body_ready_without_provider(app, user, offline, text):
    _, rows = send(user, text)
    assert len(rows) == 1
    assert rows[0].provenance_json["action_capability_id"] == "body.measurement.create"
    assert rows[0].provenance_json["step_status"] == "ready"
    assert Decimal(str(rows[0].payload_json["weight"])) == Decimal("82.5")
    assert WeighIn.query.count() == offline.calls == 0


def test_body_missing_and_single_slot(app, user, offline):
    service = AIConversationService()
    conversation = service.create(user)
    _, rows = send(user, "Registra mi peso", service, conversation)
    assert rows[0].provenance_json["step_status"] == "needs_input"
    assert rows[0].payload_json["missing_fields"] == ["weight"]
    draft_id = rows[0].public_id
    _, rows = send(user, "82.5 kg", service, conversation)
    assert rows[0].public_id == draft_id
    assert rows[0].provenance_json["step_status"] == "ready"
    assert WeighIn.query.count() == offline.calls == 0


@pytest.mark.parametrize("text,kind,target", [
    ("Cambia mi meta de pasos a 10000", "daily_steps", "10000"),
    ("Pon mi objetivo de pasos en 10000", "daily_steps", "10000"),
    ("Mi meta de proteína será 160 g", "nutrition_protein", "160"),
])
def test_goal_ready_and_never_create(app, user, offline, text, kind, target):
    goal = _goal(user, goal_type=kind)
    _, rows = send(user, text)
    assert rows[0].provenance_json["action_capability_id"] == "goal.update"
    assert rows[0].provenance_json["step_status"] == "ready"
    assert rows[0].provenance_json["action_context"]["public_id"] == goal.public_id
    assert Decimal(str(rows[0].payload_json["target_value"])) == Decimal(target)
    assert UserGoal.query.count() == 1
    assert goal.revision == 1
    assert offline.calls == 0


def test_no_provider_factory_is_constructed(app, user, offline):
    def forbidden_factory():
        raise AssertionError("No provider should even be constructed")
    app.config["AI_PROVIDER_FACTORY"] = forbidden_factory
    _, rows = send(user, "Hoy pesé 82.5 kg")
    assert rows[0].provenance_json["step_status"] == "ready"


@pytest.mark.parametrize("foreign", [False, True])
def test_selected_signed_goal_context_is_preserved(app, user, offline, foreign):
    from app.services.ai.capabilities.context import issue_action_context_token, load_action_context_token
    owner_goal = _goal(user, goal_type="daily_steps", target="9000")
    other = User(username="signed-context-qa", role="user")
    other.set_password("fictional-context-password")
    db.session.add(other)
    db.session.commit()
    other_goal = _goal(other.id, goal_type="daily_steps", target="7000")
    token = issue_action_context_token(user_id=user, action_capability_id="goal.update", domain="goals",
                                      resource_type="user_goal", resource_public_id=owner_goal.public_id)
    context = load_action_context_token(token, user_id=user).as_mapping()
    if foreign:
        context = {**context, "resource_public_id": other_goal.public_id}
    service = AIConversationService()
    conversation = service.create(user)
    def run():
        return service.send_message(_account(user), conversation.public_id, "Cambia mi meta de pasos a 10000",
                                    intent_spec=AIIntentSpec(AIIntent.CORRECT, "goals", period="today", action="goal.update"),
                                    action_context=context)
    if foreign:
        with pytest.raises(AIServiceError) as rejected:
            run()
        assert rejected.value.code == "action_context_not_found"
        assert AIActionDraft.query.count() == 0
    else:
        _, rows = run()
        assert rows[0].provenance_json["action_context"]["public_id"] == owner_goal.public_id
    assert owner_goal.revision == other_goal.revision == 1
    assert offline.calls == 0


def test_invalid_range_rejects_atomically_without_provider(app, user, offline):
    _goal(user, goal_type="daily_steps", target="9000")
    with pytest.raises(AIServiceError):
        send(user, "Registra mi peso en 900 kg y cambia mi meta de pasos a 10000")
    assert AIActionDraft.query.count() == WeighIn.query.count() == offline.calls == 0


@pytest.mark.parametrize("reply", ["82.5 kg y 10000 kg", "82.5 kg y 10000 g"])
def test_slot_units_never_dropped_by_legacy_fallback(app, user, offline, reply):
    from copy import deepcopy
    _goal(user, goal_type="daily_steps", target="9000")
    service = AIConversationService()
    conversation = service.create(user)
    _, rows = send(user, "Registra mi peso y cambia mi meta de pasos", service, conversation)
    original = [(row.public_id, deepcopy(row.payload_json), deepcopy(row.provenance_json)) for row in rows]
    with pytest.raises(AIServiceError) as error:
        send(user, reply, service, conversation)
    assert error.value.code == "invalid_action_unit"
    assert [(row.public_id, row.payload_json, row.provenance_json) for row in rows] == original
    assert offline.calls == WeighIn.query.count() == 0


def test_bare_slots_are_ambiguous_and_do_not_mutate(app, user, offline):
    _goal(user, goal_type="daily_steps", target="9000")
    service = AIConversationService()
    conversation = service.create(user)
    _, rows = send(user, "Registra mi peso y cambia mi meta de pasos", service, conversation)
    with pytest.raises(AIServiceError):
        send(user, "82.5 y 10000", service, conversation)
    assert offline.calls == 1  # interpretation is delegated, never guessed
    assert [row.provenance_json["step_status"] for row in rows] == ["needs_input"] * 2
    assert WeighIn.query.count() == 0


@pytest.mark.parametrize("count,code", [(0, "goal_not_found"), (2, "ambiguous_goal_target")])
def test_goal_missing_or_ambiguous_target(app, user, offline, count, code):
    for _ in range(count):
        _goal(user, goal_type="daily_steps")
    other = User(username="other-deterministic-qa", role="user")
    other.set_password("fictional-qa-password")
    db.session.add(other)
    db.session.commit()
    _goal(other.id, goal_type="daily_steps")
    _, rows = send(user, "Cambia mi meta de pasos a 10000")
    assert rows[0].provenance_json["action_capability_id"] == "goal.update"
    assert rows[0].provenance_json["step_status"] == "needs_input"
    assert rows[0].provenance_json["action_context"]["resolution_code"] == code
    assert "public_id" not in rows[0].provenance_json["action_context"]
    assert UserGoal.query.count() == count + 1
    assert offline.calls == 0


@pytest.mark.parametrize("text", [
    "Registra un desayuno de 500 kcal y 30 g de proteína",
    "Registra un desayuno de 500 kcal y 30 g proteína",
])
def test_food_schema_without_invented_macros(app, user, offline, text):
    _, rows = send(user, text)
    assert rows[0].provenance_json["step_status"] == "ready"
    assert rows[0].payload_json == {
        "meal_type": "breakfast", "items": [{"name": "desayuno", "calories_kcal": 500, "protein_g": 30}],
    }
    assert NutritionItem.query.count() == offline.calls == 0


@pytest.mark.parametrize("one_turn", [False, True])
def test_multi_action_provider_independent(app, user, offline, one_turn):
    goal = _goal(user, goal_type="daily_steps", target="9000")
    service = AIConversationService()
    conversation = service.create(user)
    _, rows = send(user, (
        "Registra mi peso en 82.5 kg y cambia mi meta de pasos a 10000" if one_turn
        else "Registra mi peso y cambia mi meta de pasos"
    ), service, conversation)
    assert len(rows) == 2
    ids = [row.public_id for row in rows]
    step_ids = [row.provenance_json["step_id"] for row in rows]
    assert len(set(step_ids)) == 2
    if not one_turn:
        assert [row.provenance_json["step_status"] for row in rows] == ["needs_input"] * 2
        _, rows = send(user, "82.5 kg y 10000 pasos", service, conversation)
        assert [row.public_id for row in rows] == ids
        assert [row.provenance_json["step_id"] for row in rows] == step_ids
    assert [row.provenance_json["step_status"] for row in rows] == ["ready"] * 2
    assert [row.provenance_json["action_capability_id"] for row in rows] == ["body.measurement.create", "goal.update"]
    assert AIActionDraft.query.count() == 2
    assert WeighIn.query.count() == offline.calls == 0
    assert goal.revision == 1
    assert goal.target_value == Decimal("9000")


@pytest.mark.parametrize("text", [
    "Ajústame las metas", "Ajústame mis metas", "Registra lo de hoy",
    "Creo que debería pesar menos", "Ponme una buena meta de proteína",
    "¿Cómo voy con mi meta de pasos?", "Analiza mi peso", "¿Cuánta proteína debería comer?",
    "¿Cómo voy con mi peso?", "No registra mi peso en 82.5 kg",
    "Registra mi peso en 82.5 kg si mañana bajo", "Registra mi peso en 82.5 g",
    "Cambia mi meta de pasos a 10000 kg", "Cambia mi meta de pasos a 10000 y la de proteína a 160",
    "Registra mi peso en 82.5 kg o 83 kg", "Registra mi peso en 82.5 kg y borra lo anterior",
    "Registra mi peso en 82.5 kg ayer", "Registra mi peso en 82.5 kg y 84 kg",
    "Registra mi peso en 82.5 kg y cambia la meta de otro usuario",
    "Cambia mi meta de pasos a 10000 y cambia mi meta de pasos a 12000",
])
def test_closed_grammar_declines_whole_turn(app, text):
    match = DeterministicActionInterpreter(AICapabilityRegistry()).interpret(text)
    assert not match.high_confidence
    assert match.proposal is None


def test_ambiguous_uses_provider(app, user, offline, caplog):
    with caplog.at_level(logging.INFO), pytest.raises(AIServiceError):
        send(user, "Ajústame mis metas")
    assert offline.calls == 1
    assert "action_resolution=provider" in caplog.text
    assert AIActionDraft.query.count() == WeighIn.query.count() == 0


def test_explicit_analysis_selection_cannot_become_deterministic_action(app, user, offline):
    service = AIConversationService()
    conversation = service.create(user)
    with pytest.raises(AIServiceError):
        service.send_message(_account(user), conversation.public_id, "Hoy pesé 82.5 kg",
                             intent_spec=AIIntentSpec(AIIntent.TREND, "body", period="30d"))
    assert offline.calls == 1
    assert AIActionDraft.query.count() == 0


def test_logs_do_not_contain_values_or_prompt(app, user, offline, caplog):
    _goal(user, goal_type="daily_steps", target="9000")
    with caplog.at_level(logging.INFO):
        send(user, "Registra mi peso en 82.57 kg y cambia mi meta de pasos a 12345")
    resolution = "\n".join(record.message for record in caplog.records if "ai_action_resolution" in record.message)
    assert "action_resolution=deterministic" in resolution
    assert "step_count=2" in resolution
    assert not any(value in resolution for value in ("82.57", "12345", "Registra", "payload"))


def test_future_sleep_is_discovered_without_core_changes(app, user, offline):
    action = ActionCapability(
        action_id="sleep.log", domain="sleep", entity="sleep_entry", operation="create",
        label="Registrar sueño", description="QA ficticio", supported_fields=("duration", "quality"),
        required_fields=("duration", "quality"), optional_fields=(),
        input_schema={"type": "object", "properties": {"duration": {"type": "number", "maximum": 24},
                      "quality": {"type": "integer", "minimum": 1, "maximum": 5}}, "additionalProperties": False},
        apply_handler=lambda *_: ActionApplyResult("sleep_entry", ()),
        language=(ActionLanguage(verbs=("registrar", "anotar"), entities=("sueño",), slots=(
            ActionNumericSlot("duration", aliases=("duración",), units=(("horas", "h"),), primary=True),
            ActionNumericSlot("quality", aliases=("calidad",)),
        )),),
    )
    manifest = AICapabilityManifest("sleep", "Sueño", "QA", ("sleep_entry",), (), (), (action,))
    registry = AICapabilityRegistry((*load_manifests(), manifest))
    service = AIConversationService(capability_registry=registry)
    _, rows = send(user, "Anotar sueño de 8 horas y calidad 4", service)
    assert rows[0].provenance_json["action_capability_id"] == "sleep.log"
    assert rows[0].payload_json == {"duration": 8, "quality": 4}
    assert rows[0].provenance_json["step_status"] == "ready"
    assert offline.calls == 0
    conversation = service.create(user)
    _, pending = send(user, "Registrar sueño de 8 horas", service, conversation)
    assert pending[0].provenance_json["step_status"] == "needs_input"
    assert "missing_fields" not in pending[0].payload_json  # not in this schema
    identity = pending[0].public_id
    _, complete = send(user, "calidad 4", service, conversation)
    assert complete[0].public_id == identity
    assert complete[0].provenance_json["step_status"] == "ready"
    invalid = replace(action, language=(replace(action.language[0], slots=(ActionNumericSlot("user_id", primary=True),)),))
    with pytest.raises(RuntimeError, match="unsupported schema field"):
        AICapabilityRegistry((*load_manifests(), replace(manifest, action_capabilities=(invalid,))))


def test_local_certification_and_cleanup(app, offline):
    db.session.execute(sql_text("PRAGMA foreign_keys=ON"))
    qa = User(username="temporary-local-certification-qa", role="user")
    qa.set_password("fictional-local-password")
    db.session.add(qa)
    db.session.commit()
    uid = qa.id
    try:
        _goal(uid, goal_type="daily_steps", target="9000")
        for prompt in ("Cambia mi meta de pasos a 10000", "Registra un desayuno de 500 kcal y 30 g proteína"):
            _, rows = send(uid, prompt)
            assert all(row.provenance_json["step_status"] == "ready" for row in rows)
        service = AIConversationService()
        conversation = service.create(uid)
        _, rows = send(uid, "Registra mi peso y cambia mi meta de pasos", service, conversation)
        assert len(rows) == 2
        _, rows = send(uid, "82.5 kg y 10000 pasos", service, conversation)
        assert all(row.provenance_json["step_status"] == "ready" for row in rows)
        assert WeighIn.query.filter_by(user_id=uid).count() == NutritionItem.query.filter_by(user_id=uid).count() == 0
        assert AIActionDraft.query.filter_by(user_id=uid, status="applied").count() == 0
    finally:
        db.session.delete(qa)
        db.session.commit()
    assert db.session.get(User, uid) is None
    for model in (AIConversation, AIMessage, AIToolCall, AIActionDraft, UserGoal, WeighIn, NutritionItem):
        assert model.query.filter_by(user_id=uid).count() == 0
    assert offline.calls == 0


@pytest.mark.skipif(not Path("/.dockerenv").exists() and os.getenv("AI_MARIADB_QA") != "1",
                    reason="Requires disposable local MariaDB")
def test_mariadb_deterministic_goal_slots_idempotency_cleanup(app, tmp_path):
    qa_app = create_app({
        "TESTING": True, "SECRET_KEY": "deterministic-mariadb-fictional-secret-long-enough",
        "API_TOKEN_SIGNING_KEY": "deterministic-mariadb-fictional-token-key-long-enough",
        "DATA_ROOT": tmp_path / "deterministic", "UPLOAD_ROOT": tmp_path / "deterministic/raw",
        "GENERATED_UPLOAD_ROOT": tmp_path / "deterministic/generated",
        "SCHEMA_ROOT": app.config["SCHEMA_ROOT"], "APP_TIMEZONE": "UTC",
    })
    provider = ExplodingProvider()
    _enable_ai(qa_app, provider)
    with qa_app.app_context():
        assert db.engine.dialect.name in {"mysql", "mariadb"}
        qa = User(username=f"deterministic-mariadb-qa-{uuid.uuid4().hex}", role="user")
        other = User(username=f"deterministic-mariadb-other-qa-{uuid.uuid4().hex}", role="user")
        for account in (qa, other):
            account.set_password("fictional-mariadb-password")
            db.session.add(account)
        db.session.commit()
        ids = (qa.id, other.id)
        try:
            foreign = _goal(other.id, goal_type="daily_steps", target="7000")
            _, missing = send(qa.id, "Cambia mi meta de pasos a 10000")
            assert missing[0].provenance_json["step_status"] == "needs_input"
            goal = _goal(qa.id, goal_type="daily_steps", target="9000")
            _, ready = send(qa.id, "Cambia mi meta de pasos a 10000")
            assert ready[0].provenance_json["step_status"] == "ready"
            assert ready[0].provenance_json["action_context"]["public_id"] == goal.public_id
            service = AIConversationService()
            conversation = service.create(qa.id)
            _, rows = send(qa.id, "Registra mi peso y cambia mi meta de pasos", service, conversation)
            identity = [(row.public_id, row.provenance_json["step_id"]) for row in rows]
            assert len(identity) == 2
            _, rows = send(qa.id, "82.5 kg y 10000 pasos", service, conversation)
            assert [(row.public_id, row.provenance_json["step_id"]) for row in rows] == identity
            assert all(row.provenance_json["step_status"] == "ready" for row in rows)
            assert AIActionDraft.query.filter_by(conversation_id=conversation.id).count() == 2
            assert WeighIn.query.filter_by(user_id=qa.id).count() == 0
            assert goal.revision == foreign.revision == 1
            plan_id = rows[0].provenance_json["plan_id"]
            # An explicit test confirmation exercises the unchanged apply boundary.
            assert service.confirm_plan(qa, plan_id)["counts"]["applied"] == 2
            assert service.confirm_plan(qa, plan_id)["counts"]["applied"] == 2
            assert WeighIn.query.filter_by(user_id=qa.id).count() == 1
            assert goal.revision == 2
            assert foreign.revision == 1
            assert provider.calls == 0
        finally:
            db.session.rollback()
            db.session.execute(db.delete(User).where(User.id.in_(ids)))
            db.session.commit()
        for mapper in db.Model.registry.mappers:
            model = mapper.class_
            if hasattr(model, "user_id"):
                assert db.session.execute(db.select(db.func.count()).select_from(model).where(model.user_id.in_(ids))).scalar_one() == 0
