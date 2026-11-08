"""Synthetic QA fixtures only; no personal records or remote provider calls."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import json

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import AIToolCall, DailyEnergy, DailyNutrition, User
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import AIIntent, AIIntentSpec
from app.services.ai.conversations import AIConversationService, AIServiceError
from app.services.ai.providers import AIProvider, FakeAIProvider
from app.services.ai.tools import AIToolError, AIToolRegistry
from app.services.ai.types import AIProviderCapabilities, AIProviderResponse, AIProviderToolCall
from app.services.daily_balance import daily_balance
from app.services.dashboard.date_range import DashboardDateRange
from app.services.energy_balance import EnergyBalanceService
from tests.conftest import login


@pytest.fixture
def app(app, tmp_path):
    """Optional disposable MariaDB QA, never a configurable production URI."""
    port = os.environ.get("AI_ENERGY_QA_DB_PORT")
    if not port:
        yield app
        return
    from app import create_app
    from sqlalchemy import text
    assert port.isdigit()
    config = dict(app.config)
    config.update(SQLALCHEMY_DATABASE_URI=f"mysql+pymysql://qa:fictional-qa-only@127.0.0.1:{port}/energy_balance_qa",
                  SQLALCHEMY_ENGINE_OPTIONS={"isolation_level": os.environ.get("AI_ENERGY_QA_ISOLATION", "READ COMMITTED")})
    application = create_app(config)
    with application.app_context():
        assert db.session.scalar(text("SELECT DATABASE()")) == "energy_balance_qa"
        assert db.session.scalar(text("SELECT CURRENT_USER()" )).startswith("qa@")
        assert db.session.scalar(text("SELECT @@tx_isolation")).replace("-", " ") == config["SQLALCHEMY_ENGINE_OPTIONS"]["isolation_level"]
        db.session.rollback()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def seed(owner, day, intake=None, expenditure=None, *, partial=False, source="fictional-qa"):
    if intake is not None:
        db.session.add(DailyNutrition(user_id=owner, date=day, source=source,
                                     calories=Decimal(str(intake)),
                                     nutrition_summary_json={"energy": {"state": "partial"}} if partial else None))
    if expenditure is not None:
        db.session.add(DailyEnergy(user_id=owner, date=day, source=source,
                                  total_calories=Decimal(str(expenditure)), active_calories=Decimal("600")))
    db.session.commit()


def tool(owner, start="2026-10-26", end=None, **options):
    return AIToolRegistry().execute(db.session.get(User, owner), "get_energy_balance", {
        "date_from": start, "date_to": end or start, **options,
    })


def enable_ai(app):
    app.config.update(AI_ENABLED=True, AI_PROVIDER="fake", AI_MODEL="fake-health-v1",
                      AI_PROVIDER_INSTANCE=None, AI_PROVIDER_FACTORY=None,
                      AI_RATE_LIMIT_ENABLED=False, AI_TODAY_OVERRIDE=date(2026, 11, 7))


@pytest.mark.parametrize(("intake", "spent", "balance", "known", "excluded"), [
    ("2100.123", "2450.01", "-349.887", 1, []),
    ("2100", None, None, 0, ["expenditure_unknown"]),
    (None, "2450", None, 0, ["intake_unknown"]),
    (None, None, None, 0, ["intake_unknown", "expenditure_unknown"]),
    ("0", "0", "0", 1, []),
])
def test_day_precision_missing_zero_and_daily_balance_coherence(app, client, user, intake, spent, balance, known, excluded):
    with app.app_context():
        seed(user, date(2026, 10, 26), intake, spent)
        result = tool(user, include_daily=True)
        data = result.data
        actual = data["metrics"]["balance_kcal"]
        assert (Decimal(actual) if actual is not None else None) == (Decimal(balance) if balance else None)
        assert data["coverage"]["both_known_days"] == known
        assert data["coverage"]["requested_days"] == 1
        assert data["averages"]["balance_kcal"]["days"] == known
        assert [reason for item in data["excluded_days"] for reason in item["reasons"]] == excluded
        canonical = daily_balance(user, date(2026, 10, 26))
        assert (Decimal(actual) if actual is not None else None) == canonical["balance"]
        assert len(data["daily"]) == 1
        assert any(item["evidence_kind"] == "calculated" for item in result.evidence)
        assert all("quality" not in item for item in result.evidence)
        if balance == "0":
            assert data["daily"][0]["intake_state"] == "zero"
            assert data["daily"][0]["expenditure_state"] == "zero"
    login(client)
    response = client.get("/daily-balance?date=2026-10-26")
    assert response.status_code == 200


@pytest.mark.parametrize("missing", [False, True])
def test_week_uses_paired_days_and_explicit_denominators(app, user, missing):
    with app.app_context():
        for offset in range(7):
            seed(user, date(2026, 11, 1) + timedelta(days=offset), "2000", None if missing and offset > 4 else "2500")
        data = tool(user, "2026-11-01", "2026-11-07", compare_previous=True).data
        paired = 5 if missing else 7
        assert Decimal(data["metrics"]["consumed_kcal"]) == 14000
        assert Decimal(data["metrics"]["balance_kcal"]) == -500 * paired
        assert data["averages"]["balance_kcal"]["days"] == paired
        assert data["averages"]["consumed_kcal"]["days"] == 7
        assert data["coverage"]["partial_days"] == (2 if missing else 0)
        assert (data["metrics"]["complete_balance_kcal"] is None) == missing
        assert data["period"]["previous_from"] == "2026-10-25"
        assert data["period"]["previous_to"] == "2026-10-31"
        assert data["comparison"]["deltas"]["balance_kcal"]["state"] == "unavailable"
        assert data["daily"] is None


def test_calendar_months_have_different_lengths_and_exact_averages(app, user):
    with app.app_context():
        for start, count, intake in [(date(2026, 9, 1), 30, "2100.123"), (date(2026, 10, 1), 31, "2000.123")]:
            for offset in range(count):
                seed(user, start + timedelta(days=offset), intake, "2500.01")
        data = tool(user, "2026-10-01", "2026-10-31", compare_previous=True).data
        assert data["period"]["previous_from"] == "2026-09-01"
        previous = data["comparison"]["previous"]
        assert previous["period"]["to"] == "2026-09-30"
        assert previous["coverage"]["requested_days"] == 30
        assert data["comparison"]["mode"] == "calendar_month"
        assert Decimal(data["metrics"]["balance_kcal"]) == Decimal("-499.887") * 31
        assert Decimal(data["comparison"]["deltas"]["balance_kcal"]["daily_average_delta"]) == -100
        assert data["comparison"]["deltas"]["balance_kcal"]["current_days"] == 31
        assert data["comparison"]["deltas"]["balance_kcal"]["previous_days"] == 30


@pytest.mark.parametrize(("start", "end", "previous_start", "previous_end", "mode"), [
    ("2027-01-01", "2027-01-01", "2026-12-31", "2026-12-31", "equal_days"),
    ("2027-01-01", "2027-01-31", "2026-12-01", "2026-12-31", "calendar_month"),
    ("2026-12-29", "2027-01-04", "2026-12-22", "2026-12-28", "equal_days"),
    ("2028-03-01", "2028-03-31", "2028-02-01", "2028-02-29", "calendar_month"),
    ("2026-11-01", "2026-12-31", "2026-09-01", "2026-10-31", "equal_days"),
])
def test_previous_period_boundaries(app, user, start, end, previous_start, previous_end, mode):
    with app.app_context():
        data = tool(user, start, end, compare_previous=True).data
        assert (data["period"]["previous_from"], data["period"]["previous_to"]) == (previous_start, previous_end)
        assert data["comparison"]["mode"] == mode


def test_partial_nutrition_conflicting_deleted_and_active_energy_are_not_complete(app, user):
    with app.app_context():
        seed(user, date(2026, 10, 26), "1500.123", "2400", partial=True)
        data = tool(user).data
        assert data["metrics"]["balance_kcal"] is None
        assert Decimal(data["metrics"]["consumed_kcal"]) == Decimal("1500.123")
        assert data["averages"]["consumed_kcal"]["days"] == 0
        assert data["excluded_days"][0]["reasons"] == ["intake_partial"]
        seed(user, date(2026, 10, 27), "2000", "2400")
        db.session.add(DailyEnergy(user_id=user, date=date(2026, 10, 27), source="fictional-conflict", total_calories=2600))
        db.session.commit()
        data = tool(user, "2026-10-27", include_daily=True).data
        assert data["daily"][0]["expenditure_state"] == "conflict"
        assert data["metrics"]["balance_kcal"] is None
        seed(user, date(2026, 10, 28), "2000", "2400")
        row = db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.date == date(2026, 10, 28)))
        row.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        assert tool(user, "2026-10-28").data["metrics"]["expended_kcal"] is None
        db.session.add(DailyEnergy(user_id=user, date=date(2026, 10, 29), source="fictional-active", active_calories=600))
        db.session.commit()
        assert tool(user, "2026-10-29").data["metrics"]["expended_kcal"] is None


def test_partial_comparison_labels_sample_deltas(app, user):
    with app.app_context():
        seed(user, date(2026, 10, 26), "2000", "2400")
        seed(user, date(2026, 10, 24), "1900", "2400")
        data = tool(user, "2026-10-26", "2026-10-27", compare_previous=True).data
        delta = data["comparison"]["deltas"]["balance_kcal"]
        assert Decimal(delta["daily_average_delta"]) == 100
        assert delta["current_days"] == delta["previous_days"] == 1
        assert delta["state"] == "partial_sample"
        assert data["comparison"]["complete_balance_delta_kcal"] is None


@pytest.mark.parametrize("options", [
    {"date_from": "2026-10-27", "date_to": "2026-10-26"},
    {"date_from": "2026-02-30", "date_to": "2026-03-01"},
    {"date_from": "2026-01-01", "date_to": "2027-01-02"},
    {"date_from": "1900-01-01", "date_to": "1900-01-01", "compare_previous": True},
    {"date_from": "20261026", "date_to": "2026-10-26"},
    {"date_from": "2026-10-26"},
    {"date_from": "2026-10-26", "date_to": "2026-10-26", "user_id": 999},
])
def test_invalid_arguments_rejected(app, user, options):
    with app.app_context(), pytest.raises(AIToolError):
        AIToolRegistry().execute(db.session.get(User, user), "get_energy_balance", options)


def test_owner_isolation_and_no_writes(app, user):
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100", "2450")
        other = User(username="fictional-energy-other", role="user")
        other.set_password("fictional-password")
        db.session.add(other)
        db.session.commit()
        statements = []
        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.split()[0].upper())
        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            assert tool(other.id).data["coverage"]["unknown_days"] == 1
            assert tool(user).data["coverage"]["both_known_days"] == 1
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert set(statements) == {"SELECT"}


@pytest.mark.parametrize("zone", ["America/Mexico_City", "Asia/Tokyo"])
def test_user_timezone_inclusive_dates_and_year_not_truncated(app, user, zone):
    with app.app_context():
        account = db.session.get(User, user)
        account.timezone = zone
        db.session.commit()
        seed(user, date(2028, 1, 1), "2000", "2500")
        seed(user, date(2028, 12, 31), "2100", "2500")
        data = tool(user, "2028-01-01", "2028-12-31", include_daily=True).data
        assert data["period"]["timezone"] == zone
        assert data["coverage"]["requested_days"] == 366
        assert len(data["daily"]) == 366
        assert data["daily"][0]["date"] == "2028-01-01"
        assert data["daily"][-1]["date"] == "2028-12-31"
        assert len(data["excluded_days"]) == 364
        assert Decimal(data["metrics"]["balance_kcal"]) == -900


@pytest.mark.parametrize(("prompt", "start", "end", "compare"), [
    ("¿Cuál fue mi balance del 26 de octubre?", "2026-10-26", "2026-10-26", False),
    ("¿Cuánto déficit tuve la semana pasada?", "2026-10-26", "2026-11-01", False),
    ("Compara mi consumo y gasto de este mes", "2026-11-01", "2026-11-07", True),
    ("¿Qué día tuve más superávit?", "2026-10-09", "2026-11-07", False),
    ("Dame el balance de los últimos 30 días", "2026-10-09", "2026-11-07", False),
])
@pytest.mark.parametrize("domain", [None, "energy", "nutrition", "all"])
def test_assistant_discovers_authorizes_invokes_and_uses_energy_result(app, user, caplog, prompt, start, end, compare, domain):
    enable_ai(app)
    caplog.set_level("INFO", logger="app")
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        account = db.session.get(User, user)
        account.timezone = "America/Mexico_City"
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic QA energy")
        spec = AIIntentSpec(AIIntent.SUMMARY, domain, period="30d") if domain else None
        assistant, drafts = service.send_message(account, conversation.public_id, prompt, intent_spec=spec)
        calls = db.session.scalars(db.select(AIToolCall)).all()
        assert len(calls) == 1
        assert calls[0].tool_name == "get_energy_balance"
        assert calls[0].status == "completed"
        assert calls[0].sanitized_arguments_json["date_from"] == start
        assert calls[0].sanitized_arguments_json["date_to"] == end
        assert calls[0].sanitized_arguments_json["compare_previous"] == compare
        assert calls[0].result_summary_json["period"]["timezone"] == "America/Mexico_City"
        assert "Balance de" in assistant.content
        if start <= "2026-10-26" <= end:
            assert "-349.887" in assistant.content
        assert drafts == []
    assert "2100.123" not in caplog.text


def test_energy_plan_rejects_other_tools(app, user):
    class InvalidProvider(AIProvider):
        name = "fictional-invalid-energy"
        capabilities = AIProviderCapabilities(supports_tools=True)
        def respond(self, request):
            assert [item.name for item in request.tools] == ["get_energy_balance"]
            if request.tool_results:
                assert request.tool_results[-1].error_code == "tool_not_allowed_for_intent"
                return AIProviderResponse(content="Synthetic QA: unauthorized read rejected")
            return AIProviderResponse(tool_calls=(AIProviderToolCall("qa", "get_nutrition_summary", {}),))
    enable_ai(app)
    app.config["AI_PROVIDER_INSTANCE"] = InvalidProvider()
    with app.app_context():
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic denied tool QA")
        service.send_message(db.session.get(User, user), conversation.public_id, "Balance", intent_spec=AIIntentSpec(AIIntent.SUMMARY, "energy"))
        call = db.session.scalar(db.select(AIToolCall))
        assert call.status == "rejected"
        assert call.error_code == "tool_not_allowed_for_intent"


def test_energy_plan_requires_a_tool_read(app, user):
    class NoToolProvider(AIProvider):
        name = "fictional-missing-energy-read"
        capabilities = AIProviderCapabilities(supports_tools=True)
        def respond(self, request):
            assert request.require_tool
            return AIProviderResponse(content="Synthetic QA missing read")
    enable_ai(app)
    app.config["AI_PROVIDER_INSTANCE"] = NoToolProvider()
    with app.app_context():
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic missing read QA")
        with pytest.raises(AIServiceError) as error:
            service.send_message(db.session.get(User, user), conversation.public_id, "Balance", intent_spec=AIIntentSpec(AIIntent.SUMMARY, "energy"))
        assert error.value.code == "tool_required_for_intent"


def test_provider_receives_all_366_days_after_conversation_sanitization(app, user):
    class InspectProvider(FakeAIProvider):
        def respond(self, request):
            if request.tool_results:
                assert len(request.tool_results[-1].data["daily"]) == 366
                assert request.tool_results[-1].data["daily"][-1]["date"] == "2028-12-31"
                return AIProviderResponse(content="Synthetic year QA complete")
            return AIProviderResponse(tool_calls=(AIProviderToolCall("qa", "get_energy_balance", {
                "date_from": "2028-01-01", "date_to": "2028-12-31", "include_daily": True}),))
    enable_ai(app)
    app.config["AI_PROVIDER_INSTANCE"] = InspectProvider()
    with app.app_context():
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic 366 day QA")
        service.send_message(db.session.get(User, user), conversation.public_id, "Balance diario")


def test_energy_manifest_exact_plan_and_no_duplicate_calculation(app, user):
    registry = AICapabilityRegistry()
    for intent in (AIIntent.SUMMARY, AIIntent.TREND, AIIntent.COMPARE, AIIntent.COVERAGE):
        assert registry.resolve(AIIntentSpec(intent, "energy", ("balance",), "30d")).tools == ("get_energy_balance",)
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        period = DashboardDateRange.from_query({"from": "2026-10-26", "to": "2026-10-26"}, "UTC")
        internal = EnergyBalanceService().build(user, period)
        assert internal["metrics"]["balance_kcal"] == Decimal("-349.887")
        assert isinstance(internal["metrics"]["balance_kcal"], Decimal)


@pytest.mark.parametrize("phrase", ["26/10", "26-10-2026", "26 de octubre de 2026", "2026-10-26"])
def test_responses_adapter_exposes_authorized_schema_and_roundtrips_energy(app, user, phrase):
    requests = []
    def transport(_url, _headers, body, _timeout):
        document = json.loads(body)
        requests.append(document)
        serialized = json.dumps(document, ensure_ascii=False)
        assert phrase in serialized
        assert "DD/MM" in serialized
        assert "Respond in Spanish" in serialized
        assert "Current user-local date:" in serialized
        assert document["store"] is False
        assert [item["name"] for item in document["tools"]] == ["get_energy_balance"]
        outputs = [item for item in document["input"] if item.get("type") == "function_call_output"]
        if outputs:
            result = json.loads(outputs[-1]["output"])
            assert result["data"]["metrics"]["balance_kcal"] == "-349.887"
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Synthetic cloud transport QA: -349.887 kcal"}]}]}
        assert document["tool_choice"] == "required"
        schema = document["tools"][0]["parameters"]
        assert schema["additionalProperties"] is False
        assert "user_id" not in schema["properties"]
        return {"output": [{"type": "function_call", "call_id": "synthetic-energy-cloud",
                            "name": "get_energy_balance", "arguments": json.dumps({
                                "date_from": "2026-10-26", "date_to": "2026-10-26"})}]}
    enable_ai(app)
    app.config.update(AI_PROVIDER="openai", AI_API_KEY="fictional-qa-key-never-real",
                      AI_BASE_URL="https://api.openai.com/v1", AI_HTTP_TRANSPORT=transport)
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        account = db.session.get(User, user)
        account.ai_remote_consent_enabled = True
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic cloud transport QA")
        assistant, _ = service.send_message(account, conversation.public_id, "Balance del " + phrase, intent_spec=AIIntentSpec(AIIntent.SUMMARY, "energy"))
        assert "-349.887" in assistant.content
        assert len(requests) == 2
        assert "test-user" not in json.dumps(requests)


def test_comparison_can_keep_full_intake_even_without_full_expenditure(app, user):
    with app.app_context():
        for offset in range(4):
            seed(user, date(2026, 10, 24) + timedelta(days=offset), "2000", "2400" if offset != 3 else None)
        data = tool(user, "2026-10-26", "2026-10-27", compare_previous=True).data
        assert data["comparison"]["deltas"]["consumed_kcal"]["state"] == "complete"
        assert data["comparison"]["deltas"]["expended_kcal"]["state"] == "partial_sample"
        assert data["comparison"]["deltas"]["balance_kcal"]["state"] == "partial_sample"


def test_selected_plan_carries_period_and_comparison_defaults(app, user):
    enable_ai(app)
    with app.app_context():
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic selected period QA")
        service.send_message(db.session.get(User, user), conversation.public_id, "Balance", intent_spec=AIIntentSpec(
            AIIntent.COMPARE, "energy", period="7d", comparison=True))
        call = db.session.scalar(db.select(AIToolCall))
        assert call.sanitized_arguments_json["date_from"] == "2026-11-01"
        assert call.sanitized_arguments_json["date_to"] == "2026-11-07"
        assert call.result_summary_json["period"]["previous_from"] == "2026-10-25"


def test_existing_nutrition_read_model_already_contains_energy_but_exact_tool_is_available(app, user):
    enable_ai(app)
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        data = AIToolRegistry().execute(db.session.get(User, user), "get_nutrition_summary", {"preset": "previous-month"}).data
        assert Decimal(data["metrics"]["energy"]["expended_total"]) == Decimal("2450.01")
        assert data["period"]["previous_from"] is None
        assert Decimal(tool(user).data["metrics"]["expended_kcal"]) == Decimal("2450.01")


def test_averages_retain_precision_beyond_stored_daily_scale(app, user):
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        seed(user, date(2026, 10, 27), "2100.124", "2450.01")
        data = tool(user, "2026-10-26", "2026-10-27").data
        assert Decimal(data["averages"]["consumed_kcal"]["value"]) == Decimal("2100.1235")
        assert Decimal(data["averages"]["balance_kcal"]["value"]) == Decimal("-349.8865")


def test_reconciled_duplicate_energy_is_not_summed_and_resolution_keeps_provenance(app, user):
    from app.services.energy_days import edit_day, view
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100", "2400")
        db.session.add(DailyEnergy(user_id=user, date=date(2026, 10, 26), source="fictional-second-source", total_calories=2400))
        db.session.commit()
        assert Decimal(tool(user).data["metrics"]["expended_kcal"]) == 2400
        current = view(user, date(2026, 10, 26))
        edit_day(user, current.date, current.revision, {"total_calories": Decimal("2500")})
        db.session.commit()
        result = tool(user, include_daily=True)
        assert Decimal(result.data["metrics"]["balance_kcal"]) == -400
        assert result.data["daily"][0]["sources"]["expended"] == "user_override"
        assert any(item["source"] == "user_override" and item["evidence_kind"] == "recorded" for item in result.evidence)


@pytest.mark.parametrize(("mode", "previous_start"), [("auto", "2026-10-01"), ("calendar_month", "2026-10-01"), ("equal_days", "2026-10-02")])
def test_calendar_month_and_rolling_window_can_share_dates_without_sharing_comparison(app, user, mode, previous_start):
    with app.app_context():
        data = tool(user, "2026-11-01", "2026-11-30", compare_previous=True, comparison_mode=mode).data
        assert data["period"]["previous_from"] == previous_start
        assert data["period"]["previous_to"] == "2026-10-31"


def test_calendar_mode_rejects_partial_month_and_assistant_preserves_rolling_intent(app, user):
    enable_ai(app)
    app.config["AI_TODAY_OVERRIDE"] = date(2026, 11, 30)
    with app.app_context():
        with pytest.raises(AIToolError):
            tool(user, "2026-11-01", "2026-11-07", compare_previous=True, comparison_mode="calendar_month")
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic rolling period QA")
        service.send_message(db.session.get(User, user), conversation.public_id, "Compara el balance de los últimos 30 días")
        call = db.session.scalar(db.select(AIToolCall))
        assert call.sanitized_arguments_json["comparison_mode"] == "equal_days"
        assert call.result_summary_json["period"]["previous_from"] == "2026-10-02"


@pytest.mark.parametrize(("phrase", "start", "end"), [
    ("26/10", "2026-10-26", "2026-10-26"),
    ("26-10-2026", "2026-10-26", "2026-10-26"),
    ("26 de octubre de 2026", "2026-10-26", "2026-10-26"),
    ("2026-10-26", "2026-10-26", "2026-10-26"),
    ("ayer", "2026-11-07", "2026-11-07"),
    ("hoy", "2026-11-08", "2026-11-08"),
    ("semana pasada", "2026-10-26", "2026-11-01"),
    ("últimos 7 días", "2026-11-02", "2026-11-08"),
    ("últimos 30 días", "2026-10-10", "2026-11-08"),
    ("octubre de 2026", "2026-10-01", "2026-10-31"),
    ("compara octubre contra septiembre", "2026-10-01", "2026-10-31"),
])
@pytest.mark.parametrize("context", ["free", "energy", "nutrition", "all", "compare"])
def test_mission_date_grammar_runs_through_conversation(app, user, phrase, start, end, context):
    enable_ai(app)
    app.config["AI_TODAY_OVERRIDE"] = date(2026, 11, 8)
    with app.app_context():
        seed(user, date(2026, 10, 26), "2100.123", "2450.01")
        account = db.session.get(User, user)
        account.timezone = "America/Mexico_City"
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic mission date QA")
        spec = (None if context == "free" else
                AIIntentSpec(AIIntent.COMPARE, "energy", period="30d", comparison=True) if context == "compare" else
                AIIntentSpec(AIIntent.SUMMARY, context, period="30d"))
        service.send_message(account, conversation.public_id, "Balance energético: " + phrase, intent_spec=spec)
        call = db.session.scalar(db.select(AIToolCall))
        assert call.status == "completed"
        assert call.tool_name == "get_energy_balance"
        assert call.sanitized_arguments_json["date_from"] == start
        assert call.sanitized_arguments_json["date_to"] == end
        assert call.result_summary_json["period"]["timezone"] == "America/Mexico_City"
        if "compara octubre" in phrase:
            assert call.result_summary_json["period"]["previous_from"] == "2026-09-01"
            assert call.result_summary_json["period"]["previous_to"] == "2026-09-30"


@pytest.mark.parametrize("phrase", ["31/02/2026", "2026-02-30", "compara octubre contra agosto"])
def test_mission_invalid_fake_dates_are_safe_errors(app, user, phrase):
    enable_ai(app)
    with app.app_context():
        service = AIConversationService()
        conversation = service.create(user, title="Synthetic invalid date QA")
        with pytest.raises(AIServiceError) as error:
            service.send_message(db.session.get(User, user), conversation.public_id, "Balance: " + phrase)
        assert error.value.code == "invalid_energy_period"
        assert error.value.status == 422
        assert db.session.scalar(db.select(db.func.count()).select_from(AIToolCall)) == 0
