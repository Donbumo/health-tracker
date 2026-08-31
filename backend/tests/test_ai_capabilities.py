from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import AIToolCall, DailyNutrition, NutritionItem, NutritionMeal, User
from app.services.ai.capabilities.composer import (
    AdaptivePromptComposer,
    AdaptiveTemplateComposer,
)
from app.services.ai.capabilities.domains.goals import GOAL_ACTION_FOUNDATION
from app.services.ai.capabilities.domains.training import TRAINING_ACTION_FOUNDATION
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    AIIntentSpec,
    CapabilityError,
    DataAvailability,
    MetricDefinition,
    ReadCapability,
)
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import AIProvider
from app.services.ai.template_registry import AITemplateRegistry
from app.services.ai.tools import AIToolRegistry
from app.services.ai.types import (
    AIProviderCapabilities,
    AIProviderRequest,
    AIProviderResponse,
    AIToolCapabilityMetadata,
    AIToolDefinition,
)
from app.services.exercise_progress import ExerciseProgressService
from tests.conftest import login
from tests.test_mobile_progress import _plan, _session


def _enable_fake_ai(app):
    app.config.update(
        AI_ENABLED=True,
        AI_PROVIDER="fake",
        AI_MODEL="fake-health-v1",
        AI_PROVIDER_INSTANCE=None,
        AI_PROVIDER_FACTORY=None,
        AI_RATE_LIMIT_ENABLED=False,
        AI_TODAY_OVERRIDE=date(2026, 8, 30),
    )


def test_registry_exposes_typed_manifests_metrics_and_deterministic_plans():
    registry = AICapabilityRegistry()
    assert {item.domain_id for item in registry.manifests} == {
        "all",
        "energy",
        "nutrition",
        "body",
        "activity",
        "training",
        "goals",
        "data",
    }
    assert len(registry.metric_catalog) == 31
    assert registry.metric_catalog["body.weight"].unit == "user_weight_unit"
    assert registry.metric_catalog["energy.balance"].missing_data_semantics == (
        "requires_intake_and_expenditure"
    )

    plan = registry.resolve(
        AIIntentSpec(AIIntent.TREND, "body", ("weight",), "30d")
    )
    assert plan.tools == ("get_weight_trend",)
    assert {item.name for item in registry.definitions_for(plan)} == {
        "get_weight_trend"
    }


def test_manifest_validation_rejects_duplicate_domains_and_metrics():
    registry = AICapabilityRegistry()
    body = registry.manifest("body")
    with pytest.raises(RuntimeError, match="domain ids must be unique"):
        AICapabilityRegistry((body, body))
    duplicate_metrics = replace(body, metrics=(body.metrics[0], body.metrics[0]))
    with pytest.raises(RuntimeError, match="Duplicate metric"):
        AICapabilityRegistry((duplicate_metrics,))


@pytest.mark.parametrize(
    ("spec", "code"),
    (
        (AIIntentSpec(AIIntent.TREND, "body", ("not_real",), "30d"), "unsupported_metric"),
        (AIIntentSpec(AIIntent.TREND, "body", ("weight",), "today"), "unsupported_combination"),
        (AIIntentSpec(AIIntent.SUMMARY, "all", ("weight",), "30d"), "invalid_intent_metrics"),
        (AIIntentSpec(AIIntent.SUMMARY, "energy", period="30d", action="record_food"), "invalid_action_intent"),
        (AIIntentSpec(AIIntent.TREND, "body", ("weight",), "365d"), "invalid_intent_period"),
    ),
)
def test_intent_validation_rejects_unsupported_combinations(spec, code):
    with pytest.raises(CapabilityError) as error:
        AICapabilityRegistry().resolve(spec)
    assert error.value.code == code


def test_all_41_legacy_ids_are_presets_over_the_typed_engine():
    registry = AITemplateRegistry()
    assert len(registry.templates) == 41
    assert all(item.available for item in registry.templates)
    assert registry.intent_spec("period-summary", "90d") == AIIntentSpec(
        AIIntent.SUMMARY, "all", period="90d"
    )
    assert registry.intent_spec("food-patterns", "30d").intent == AIIntent.PATTERNS
    assert registry.intent_spec("exercise-progress", "90d").metrics == (
        "exercise_load",
        "volume",
        "reps",
    )


def test_prompt_composer_uses_metric_semantics_and_action_safety_without_values():
    composer = AdaptivePromptComposer()
    analysis = composer.compose(
        AIIntentSpec(AIIntent.TREND, "body", ("weight",), "30d")
    )
    assert "Peso [user_weight_unit" in analysis
    assert "ausencia: unknown_not_zero" in analysis
    assert "get_weight_trend" not in analysis
    action = composer.compose(
        AIIntentSpec(
            AIIntent.RECORD,
            "nutrition",
            period="today",
            action="record_food",
        )
    )
    assert "Nunca guardes nada automáticamente" in action
    assert "confirmación explícita" in action
    assert "83.4" not in action


def test_compare_intents_return_the_previous_equivalent_period(app, user):
    _enable_fake_ai(app)
    with app.app_context():
        account = db.session.get(User, user)
        for tool_name in ("get_weight_trend", "get_nutrition_summary"):
            result = AIToolRegistry().execute(
                account,
                tool_name,
                {"preset": "30d", "compare_previous": True},
            )
            assert result.data["comparison"]["period"]["days"] == 30
            assert result.data["comparison"]["period"]["to"] < result.data["period"]["from"]


def test_capability_availability_and_user_data_availability_are_separate(app, user):
    with app.app_context():
        catalog = AdaptiveTemplateComposer().build(user, period="30d")
        protein = next(
            item
            for item in catalog.experiences
            if item.spec.domain == "nutrition"
            and item.spec.intent == AIIntent.CONSISTENCY
            and item.spec.metrics == ("protein",)
        )
        assert protein.availability == "no_data"
        assert AICapabilityRegistry().resolve(protein.spec).tools == (
            "get_nutrition_summary",
        )
        assert catalog.recommendations[0].spec.domain == "all"
        assert all(item.spec.domain != "training" for item in catalog.recommendations)
        assert catalog.build_ms >= catalog.availability_ms >= 0
        assert catalog.recommendations_ms >= 0


def test_new_sleep_manifest_generates_experiences_without_new_presets():
    sleep_manifest = AICapabilityManifest(
        domain_id="sleep",
        label="Sueño",
        description="Sueño registrado por fuentes compatibles.",
        entities=("sleep_session",),
        metrics=(
            MetricDefinition(
                "sleep_duration",
                "Duración del sueño",
                "minutes",
                ("average", "sum"),
                True,
                True,
                False,
                0,
                "unknown_not_zero",
            ),
        ),
        read_capabilities=(
            ReadCapability(AIIntent.SUMMARY, ("get_sleep_summary",), ("sleep_duration",)),
            ReadCapability(
                AIIntent.TREND,
                ("get_sleep_summary",),
                ("sleep_duration",),
                ("7d", "30d", "90d"),
                2,
            ),
            ReadCapability(
                AIIntent.COMPARE,
                ("get_sleep_summary",),
                ("sleep_duration",),
                ("7d", "30d", "90d"),
                2,
            ),
        ),
        comparisons=True,
    )

    class SleepTools:
        definitions = (
            AIToolDefinition(
                "get_sleep_summary",
                "Resumen owner-only de sueño ficticio.",
                {"type": "object", "additionalProperties": False},
                AIToolCapabilityMetadata(
                    ("sleep",),
                    ("sleep_session",),
                    ("sleep_duration",),
                    ("summary", "trend", "compare"),
                ),
            ),
        )

    registry = AICapabilityRegistry((sleep_manifest,), tool_registry=SleepTools())
    experiences = AdaptiveTemplateComposer(registry).experiences(
        period="30d",
        availability={"sleep": DataAvailability("sleep", 12, "available")},
    )
    assert {(item.spec.intent, item.spec.metrics) for item in experiences} == {
        (AIIntent.SUMMARY, ()),
        (AIIntent.TREND, ("sleep_duration",)),
        (AIIntent.COMPARE, ("sleep_duration",)),
    }
    assert len(AITemplateRegistry().templates) == 41


def test_food_patterns_are_real_aggregates_owner_only_with_provenance(app, user):
    _enable_fake_ai(app)
    with app.app_context():
        other = User(username="food-pattern-other", role="user")
        other.set_password("fictional-food-pattern-password")
        db.session.add(other)
        db.session.flush()

        owner_day = DailyNutrition(
            user_id=user,
            date=date(2026, 8, 25),
            source="manual",
            calories="500",
            protein_g="35",
        )
        foreign_day = DailyNutrition(
            user_id=other.id,
            date=date(2026, 8, 25),
            source="manual",
            calories="999",
            protein_g="99",
        )
        db.session.add_all((owner_day, foreign_day))
        db.session.flush()
        owner_meal = NutritionMeal(
            user_id=user,
            daily_nutrition=owner_day,
            meal_type="breakfast",
            name="Desayuno QA ficticio",
            sort_order=1,
        )
        foreign_meal = NutritionMeal(
            user_id=other.id,
            daily_nutrition=foreign_day,
            meal_type="dinner",
            name="Cena ajena QA ficticia",
            sort_order=1,
        )
        db.session.add_all((owner_meal, foreign_meal))
        db.session.flush()
        db.session.add_all(
            (
                NutritionItem(
                    user_id=user,
                    meal=owner_meal,
                    name="Avena QA ficticia",
                    sort_order=1,
                    source="manual",
                ),
                NutritionItem(
                    user_id=other.id,
                    meal=foreign_meal,
                    name="Dato ajeno QA ficticio",
                    sort_order=1,
                    source="manual",
                ),
            )
        )
        db.session.commit()
        account = db.session.get(User, user)
        result = AIToolRegistry().execute(account, "get_food_patterns", {"preset": "30d"})
        names = [item["name"] for item in result.data["repeated_items"]]
        assert names == ["Avena QA ficticia"]
        assert result.data["frequency"]["days_with_records"] == 1
        assert result.data["recorded_hours"]["available"] is False
        assert any(item["source"] == "manual" for item in result.evidence)
        assert "Dato ajeno" not in str(result.data)


def test_exercise_progress_is_owner_only_and_does_not_compare_incompatible_loads(app, user):
    with app.app_context():
        now = datetime.now(timezone.utc)
        owner_plan, owner_version = _plan(user, "Plan adaptativo QA ficticio")
        _session(
            user,
            owner_plan,
            owner_version,
            now - timedelta(days=2),
            exercise_name="Press QA ficticio",
            weight="40",
            reps=8,
        )
        _session(
            user,
            owner_plan,
            owner_version,
            now - timedelta(days=1),
            exercise_name="Flexión QA ficticia",
            weight="0",
            reps=12,
            load_mode="bodyweight",
        )
        other = User(username="exercise-progress-other", role="user")
        other.set_password("fictional-exercise-progress-password")
        db.session.add(other)
        db.session.flush()
        other_plan, other_version = _plan(other.id, "Plan ajeno adaptativo QA")
        _session(
            other.id,
            other_plan,
            other_version,
            now,
            exercise_name="Ejercicio ajeno QA ficticio",
            weight="200",
            reps=20,
        )
        db.session.commit()

        service = ExerciseProgressService()
        summary = service.build(user, "30d")
        assert {item["name"] for item in summary["exercises"]} == {
            "Press QA ficticio",
            "Flexión QA ficticia",
        }
        assert "Ejercicio ajeno" not in str(summary)
        bodyweight = service.build(user, "30d", exercise="Flexión QA ficticia")
        assert bodyweight["coverage"]["comparable"] is False
        assert bodyweight["exercise"]["best_load_kg"] is None
        assert all(point["best_load_kg"] is None for point in bodyweight["points"])
        assert "session_public_id" not in str(bodyweight)


def test_action_metadata_reports_real_actions_and_honest_future_blockers():
    actions = {item.action_id: item for item in AICapabilityRegistry().action_capabilities}
    assert set(actions) == {"record_food", "record_measurement", "correct_measurement"}
    assert all(item.confirmation_required for item in actions.values())
    assert TRAINING_ACTION_FOUNDATION.available is False
    assert "plan/version" in TRAINING_ACTION_FOUNDATION.blocker
    assert GOAL_ACTION_FOUNDATION.available is False
    assert "draft" in GOAL_ACTION_FOUNDATION.blocker.casefold()


def test_structured_web_flow_prepares_without_provider_and_rejects_tampering(
    app, client, user
):
    _enable_fake_ai(app)
    app.config["AI_PROVIDER_FACTORY"] = lambda: pytest.fail(
        "preparing a structured intent must not initialize the provider"
    )
    login(client)
    preview = client.get(
        "/ai",
        query_string={
            "intent": "trend",
            "domain": "body",
            "metric": "weight",
            "period": "30d",
            "tool": "execute_sql",
            "user_id": "999999",
        },
    )
    html = preview.get_data(as_text=True)
    assert preview.status_code == 200
    assert "Mensaje preparado" in html
    assert "Tendencia · Cuerpo" in html
    assert 'name="intent" value="trend"' in html
    assert 'name="metric" value="weight"' in html
    assert "execute_sql" not in html
    assert "999999" not in html
    assert client.get(
        "/ai",
        query_string={
            "intent": "trend",
            "domain": "body",
            "metric": "private_metric",
            "period": "30d",
        },
    ).status_code == 409


def test_structured_turn_uses_only_planned_tool_and_logs_no_health_value(
    app, user, caplog
):
    _enable_fake_ai(app)
    caplog.set_level("INFO", logger="app")
    with app.app_context():
        account = db.session.get(User, user)
        conversation = AIConversationService().create(user, title="QA adaptativo")
        spec = AIIntentSpec(AIIntent.TREND, "body", ("weight",), "30d")
        _assistant, drafts = AIConversationService().send_message(
            account,
            conversation.public_id,
            "Peso ficticio sensible 83.456 kg; analiza la tendencia.",
            intent_spec=spec,
        )
        calls = db.session.execute(db.select(AIToolCall)).scalars().all()
        assert [item.tool_name for item in calls] == ["get_weight_trend"]
        assert drafts == []
    assert "intent=trend" in caplog.text
    assert "domain=body" in caplog.text
    assert "83.456" not in caplog.text


def test_structured_read_rejects_provider_answer_without_required_tool(app, user):
    class NoToolProvider(AIProvider):
        name = "no-tool-qa"
        capabilities = AIProviderCapabilities(supports_tools=True)

        def respond(self, request: AIProviderRequest) -> AIProviderResponse:
            assert request.require_tool is True
            assert [item.name for item in request.tools] == ["get_weight_trend"]
            return AIProviderResponse(content="Respuesta QA sin consultar datos.")

    _enable_fake_ai(app)
    app.config["AI_PROVIDER_INSTANCE"] = NoToolProvider()
    with app.app_context():
        account = db.session.get(User, user)
        conversation = AIConversationService().create(user, title="QA tool obligatoria")
        with pytest.raises(AIServiceError) as error:
            AIConversationService().send_message(
                account,
                conversation.public_id,
                "Analiza mi peso.",
                intent_spec=AIIntentSpec(
                    AIIntent.TREND, "body", ("weight",), "30d"
                ),
            )
        assert error.value.code == "tool_required_for_intent"
