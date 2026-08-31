import re
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import AIConversation, AIMessage, AIToolCall, NutritionItem, User, WeighIn
from app.services.ai.conversations import AIConversationService
from app.services.ai.template_registry import (
    AITemplateError,
    AITemplateRegistry,
    PERIOD_ORDER,
)
from tests.conftest import login


def _enable_fake_ai(app):
    app.config.update(
        AI_ENABLED=True,
        AI_PROVIDER="fake",
        AI_MODEL="fake-health-v1",
        AI_PROVIDER_INSTANCE=None,
        AI_PROVIDER_FACTORY=None,
        AI_RATE_LIMIT_ENABLED=False,
    )


def test_registry_has_complete_unique_stably_sorted_declarative_catalog():
    registry = AITemplateRegistry()
    entries = registry.templates
    templates = [entry.template for entry in entries]

    assert len(templates) == 41
    assert len({item.id for item in templates}) == 41
    assert [item.sort_order for item in templates] == sorted(
        item.sort_order for item in templates
    )
    assert {item.category for item in templates} == {
        "summary",
        "energy",
        "nutrition",
        "body",
        "activity",
        "training",
        "goals",
        "data",
        "log",
    }
    assert {item.mode for item in templates} == {"analysis", "comparison", "action"}
    assert all(callable(item.prompt_builder) for item in templates)
    assert all(item.default_period in item.allowed_periods for item in templates)
    assert all(set(item.allowed_periods) <= set(PERIOD_ORDER) for item in templates)
    assert all(item.required_capabilities for item in templates)
    assert all(item.token for item in templates)
    assert {
        "Comparar con anterior",
        "Ver solo balance",
        "Revisar días faltantes",
        "Analizar proteína",
        "Ver tendencia de peso",
        "Explicar fuentes",
    } <= {item.title for item in templates}


def test_registry_all_legacy_presets_are_backed_by_real_capabilities():
    registry = AITemplateRegistry()
    unavailable = {
        entry.template.id: entry.missing_capabilities
        for entry in registry.templates
        if not entry.available
    }
    assert unavailable == {}
    assert registry.get("food-patterns").template.intent_spec().domain == "nutrition"
    assert registry.get("exercise-progress").template.intent_spec().domain == "training"


def test_prompt_builders_are_deterministic_server_side_and_contain_no_fixture_health_data():
    registry = AITemplateRegistry()
    forbidden = (
        "83.4",
        "74.5",
        "130 kcal",
        "test-user",
        "demo@example.com",
        "client_event_id",
    )
    for entry in registry.templates:
        item = entry.template
        for period in item.allowed_periods:
            first = item.build_prompt(period)
            second = item.build_prompt(period)
            assert first == second
            assert len(first) < 4000
            assert not any(value in first for value in forbidden)
            assert "razonamiento interno" in first
            if item.mode == "action":
                assert "Nunca guardes nada automáticamente" in first
                assert "confirmación explícita" in first
            else:
                assert "cobertura de datos" in first
                assert "fuentes" in first


def test_registry_rejects_unknown_template_and_invalid_period():
    registry = AITemplateRegistry()
    with pytest.raises(AITemplateError) as unknown:
        registry.get("not-a-template")
    assert unknown.value.status == 404
    with pytest.raises(AITemplateError) as invalid_period:
        registry.prepare("weekly-summary", "90d")
    assert invalid_period.value.code == "invalid_template_period"


def test_action_templates_expose_only_existing_draft_fields():
    registry = AITemplateRegistry()
    food = registry.get("log-food").template.input_schema
    body = registry.get("log-body-composition").template.input_schema
    correction = registry.get("correct-body-measurement").template
    assert set(food["properties"]) == {"date", "meal_type", "meal_name", "items"}
    assert set(body["properties"]) == {
        "weight",
        "unit",
        "recorded_at",
        "body_fat_percent",
        "muscle_mass_kg",
        "water_percent",
        "visceral_fat",
        "bmr_kcal",
        "bmi",
        "notes",
    }
    assert correction.required_capabilities == (
        "draft:body_measurement",
        "action:correct_measurement",
    )


def test_catalog_and_template_preview_render_without_provider_or_health_read_models(
    app, client, user, monkeypatch
):
    _enable_fake_ai(app)
    app.config["AI_PROVIDER_FACTORY"] = lambda: pytest.fail(
        "catalog and preview must not initialize the provider"
    )
    login(client)
    page = client.get("/ai")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert html.count("data-ai-template-card") == 41
    assert "¿Qué quieres hacer?" in html
    assert "Resumen" in html
    assert "Energía" in html
    assert "Registrar" in html
    assert "AI Capability Engine" in html
    assert "Recomendado para ti" in html
    assert "Capacidades por dominio" in html
    assert "Accesos rápidos compatibles · 41 presets" in html
    assert "ai_templates.js?v=3.0" in html
    assert client.get("/ai/templates").status_code == 200

    preview = client.get(
        "/ai", query_string={"template": "energy-balance", "period": "30d"}
    )
    preview_html = preview.get_data(as_text=True)
    assert preview.status_code == 200
    assert "Mensaje preparado" in preview_html
    assert "Continuar sin enviar" in preview_html
    assert "Analiza mi balance energético" in preview_html
    with app.app_context():
        assert db.session.execute(db.select(AIConversation)).scalars().all() == []
        assert db.session.execute(db.select(AIMessage)).scalars().all() == []


def test_template_prepare_creates_empty_owner_scoped_conversation_without_auto_send(
    app, client, user
):
    _enable_fake_ai(app)
    login(client)
    prepared = AITemplateRegistry().prepare("period-summary", "30d")[2]
    response = client.post(
        "/ai/conversations",
        data={
            "template_id": "period-summary",
            "period": "30d",
            "content": prepared,
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert prepared in html
    assert "Enviar" in html
    with app.app_context():
        conversation = db.session.execute(db.select(AIConversation)).scalar_one()
        conversation_id = conversation.public_id
        assert conversation.user_id == user
        assert conversation.messages == []

        other = User(username="template-other", role="user")
        other.set_password("fictional-template-password")
        db.session.add(other)
        db.session.commit()
    client.post("/logout")
    login(client, "template-other", "fictional-template-password")
    assert client.get(f"/ai/conversations/{conversation_id}").status_code == 404


@pytest.mark.parametrize(
    ("template_id", "expected_tool"),
    (
        ("period-summary", "get_dashboard_summary"),
        ("energy-balance", "get_dashboard_summary"),
        ("nutrition-overview", "get_nutrition_summary"),
        ("weight-trend", "get_weight_trend"),
        ("activity-overview", "get_activity_summary"),
        ("training-summary", "get_training_summary"),
        ("goals-overview", "get_goals_summary"),
        ("data-quality", "get_dashboard_summary"),
    ),
)
def test_fake_provider_template_families_select_existing_tools_and_handle_results(
    app, user, template_id, expected_tool
):
    _enable_fake_ai(app)
    with app.app_context():
        account = db.session.get(User, user)
        template, period, prompt = AITemplateRegistry().prepare(template_id)
        conversation = AIConversationService().create(user, title=template.title)
        assistant, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            prompt,
            template_id=template.id,
        )
        call = db.session.execute(db.select(AIToolCall)).scalar_one()
        assert call.tool_name == expected_tool
        assert call.result_summary_json is not None
        assert assistant.role == "assistant"
        assert assistant.content
        assert any(
            item.get("evidence_kind") == "ai_interpretation"
            for item in assistant.evidence_json
        )
        assert drafts == []
        assert period == template.default_period


@pytest.mark.parametrize(
    ("template_id", "reported_values", "draft_type"),
    (
        (
            "log-food",
            "Alimento QA ficticio, 130 kcal, 30 g proteína; fue hoy desayuno",
            "food_entry",
        ),
        (
            "log-body-composition",
            "Hoy pesé 83.4 kg y 23.9% grasa corporal",
            "body_measurement",
        ),
    ),
)
def test_fake_provider_action_templates_stop_at_editable_draft(
    app, user, template_id, reported_values, draft_type
):
    _enable_fake_ai(app)
    with app.app_context():
        account = db.session.get(User, user)
        template, _, prompt = AITemplateRegistry().prepare(template_id)
        conversation = AIConversationService().create(user, title=template.title)
        _, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            f"{prompt}\n{reported_values}",
            template_id=template.id,
        )
        assert len(drafts) == 1
        assert drafts[0].draft_type == draft_type
        assert drafts[0].status == "pending_confirmation"
        assert db.session.execute(db.select(NutritionItem)).scalars().all() == []
        assert db.session.execute(db.select(WeighIn)).scalars().all() == []


def test_correction_template_reuses_owner_only_patch_and_is_idempotent(app, user):
    _enable_fake_ai(app)
    with app.app_context():
        account = db.session.get(User, user)
        original = WeighIn(
            user_id=user,
            recorded_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            weight_kg="83.400",
            source="manual",
        )
        db.session.add(original)
        db.session.commit()
        original_id = original.public_id

        template, _, prompt = AITemplateRegistry().prepare(
            "correct-body-measurement"
        )
        conversation = AIConversationService().create(user, title=template.title)
        _, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            f"{prompt}\nPeso 83.2 kg y 23.7% grasa corporal.",
            template_id=template.id,
        )
        assert len(drafts) == 1
        draft = drafts[0]
        assert draft.status == "pending_confirmation"
        assert draft.provenance_json["correction_target"]["public_id"] == original_id
        assert (
            db.session.execute(db.select(WeighIn)).scalars().one().weight_kg
            == Decimal("83.400")
        )

        first = AIConversationService().confirm_draft(account, draft.public_id)
        second = AIConversationService().confirm_draft(account, draft.public_id)
        assert first.public_id == second.public_id
        records = db.session.execute(db.select(WeighIn)).scalars().all()
        assert len(records) == 1
        assert str(records[0].weight_kg) == "83.200"
        assert str(records[0].body_fat_percentage) == "23.700"
        assert records[0].revision == 2


def test_template_routes_reject_unknown_ids_and_invalid_periods(app, client, user):
    _enable_fake_ai(app)
    login(client)
    assert client.get("/ai?template=unknown&period=30d").status_code == 404
    assert client.get("/ai?template=weekly-summary&period=90d").status_code == 400


def test_compatible_followups_prefill_without_creating_or_sending_another_turn(
    app, client, user
):
    _enable_fake_ai(app)
    login(client)
    template, period, prompt = AITemplateRegistry().prepare("period-summary", "30d")
    client.post(
        "/ai/conversations",
        data={"template_id": template.id, "period": period, "content": prompt},
    )
    with app.app_context():
        conversation_id = db.session.execute(db.select(AIConversation)).scalar_one().public_id
    answer = client.post(
        f"/ai/conversations/{conversation_id}/messages",
        data={
            "content": prompt,
            "template_id": template.id,
            "period": period,
        },
        follow_redirects=True,
    )
    html = answer.get_data(as_text=True)
    assert "También puedes:" in html
    assert "Comparar con anterior" in html
    assert "Ver solo balance" in html
    assert "Revisar días faltantes" in html
    assert "no se envía automáticamente" in html
    assert "data-ai-followup-prompt" in html

    client.get("/ai?template=compare-periods&period=30d")
    with app.app_context():
        assert db.session.execute(db.select(AIConversation)).scalars().all().__len__() == 1
        assert db.session.execute(db.select(AIMessage)).scalars().all().__len__() == 2


def test_dashboard_and_today_use_non_sensitive_structured_deep_links(app, client, user):
    _enable_fake_ai(app)
    login(client)
    dashboard = client.get("/dashboard?period=90").get_data(as_text=True)
    assert "intent=summary&amp;domain=all&amp;period=90d" in dashboard
    assert "intent=summary&amp;domain=energy&amp;metric=balance&amp;period=90d" in dashboard
    assert "intent=trend&amp;domain=body&amp;metric=weight&amp;period=90d" in dashboard
    assert "intent=summary&amp;domain=activity&amp;period=90d" in dashboard
    assert "intent=summary&amp;domain=training&amp;period=90d" in dashboard
    assert not re.search(r"(?:prompt|start|end)=", dashboard)

    today = client.get("/today").get_data(as_text=True)
    assert "Analizar hoy con IA" in today
    assert "intent=summary&amp;domain=all&amp;period=today" in today
