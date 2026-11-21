"""Fictitious QA inputs only; no production data or dependency on PR #47."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import DailyNutrition, User, UserGoal, WeighIn
from app.services import food_catalog, nutrition_intelligence as ni
from app.services.dashboard import DashboardDateRange, DashboardSummaryService
from app.services.demo_goals import DEMO_EMAIL, DEMO_PUBLIC_ID, SPECS, seed_demo_goals
from app.services.engagement import adherence_summary, create_goal, patch_goal
from app.services.mobile_health import health_progress, health_today, serialize_nutrition_day
from app.services.nutrition_math import ingredient, summarize
from tests.conftest import login


def period(start="2026-10-01", end="2026-10-07"):
    return DashboardDateRange.from_query({"from": start, "to": end}, "UTC")


def goal(owner, start="2026-10-01", value=265):
    return create_goal(owner, {"goal_type": "nutrition_carbohydrates", "target_value": value,
                              "unit": "g", "period": "daily", "timezone": "UTC", "start_date": start})


@pytest.fixture
def demo(app):
    app.config.update(DEMO_GOALS_ENABLED=True, DEMO_GOALS_ENVIRONMENT="test")
    row = User(public_id=DEMO_PUBLIC_ID, username=DEMO_EMAIL, email=DEMO_EMAIL,
               display_name="Health Tracker Demo", role="user", timezone="UTC")
    row.set_password("Fictitious-QA-password-only")
    db.session.add(row)
    db.session.commit()
    return row.id


@pytest.mark.parametrize("total,net", [(265, None), (265, 230), (None, 230)])
def test_carb_identity_in_daily_weekly_dashboard_mobile_and_export(app, client, user, total, net):
    for offset in range(7):
        db.session.add(DailyNutrition(user_id=user, date=date(2026, 10, 1)+timedelta(days=offset),
                                     source="manual", total_carbs_g=total, net_carbs_g=net))
    goal(user)
    other = User(username="QA other carb owner", role="user")
    other.set_password("QA-password-only")
    db.session.add(other)
    db.session.flush()
    db.session.add(DailyNutrition(user_id=other.id, date=date(2026, 10, 1), total_carbs_g=999, source="manual"))
    db.session.commit()
    result = DashboardSummaryService().build(user, period(), "kg")
    averages = result["summary"]["nutrition"]["averages"]
    assert averages["total_carbs"]["average"] == ("265.00" if total else None)
    assert averages["net_carbs"]["average"] == ("230.00" if net else None)
    assert averages["net_carbs"]["goal"] is None
    assert averages["total_carbs"]["percent_of_goal"] == ("100.00" if total else None)
    assert result["goals"][0]["actual"] == ("265.00" if total else None)
    today = health_today(user, date(2026, 10, 1), "UTC")
    assert today["nutrition"]["totals"]["carbohydrate_g"] == ("265" if total else None)
    assert today["nutrition"]["remaining"]["carbohydrate_g"] == ("0" if total else None)
    points = health_progress(user, date(2026, 10, 1), date(2026, 10, 7), "UTC")["points"]
    assert all(p["carbohydrate_g"] == ("265" if total else None) for p in points)
    day = serialize_nutrition_day(user, date(2026, 10, 1))
    assert day["totals"]["net_carbs_g"] == ("230" if net else None)
    login(client)
    response = client.get("/dashboard?from=2026-10-01&to=2026-10-07")
    assert response.status_code == 200
    assert "Carbohidratos totales" in response.text and "Carbohidratos netos" in response.text
    row = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id == user, DailyNutrition.date == date(2026, 10, 1)))
    exported = client.get(f"/daily-nutrition/{row.id}/export/json")
    assert exported.status_code == 200
    assert "999" not in exported.text
    exported_data = exported.get_json()["data"]
    assert exported_data.get("total_carbs_g") == total
    assert exported_data.get("net_carbs_g") == net
    for url in ("/daily-nutrition", f"/daily-nutrition/{row.id}", "/daily-balance?date=2026-10-01"):
        response = client.get(url)
        assert response.status_code == 200
        assert "Carbohidratos totales" in response.text and "Carbohidratos netos" in response.text


def test_partial_and_goal_day_populations_are_not_mixed(app, user):
    goal(user, start="2026-10-03")
    for offset, carbs in enumerate([999, 999, 265, 265, 265, 265, 265]):
        db.session.add(DailyNutrition(user_id=user, date=date(2026, 10, 1)+timedelta(days=offset),
                                     source="manual", total_carbs_g=carbs, net_carbs_g=10))
    db.session.commit()
    result = DashboardSummaryService().build(user, period(), "kg")
    item = result["summary"]["nutrition"]["averages"]["total_carbs"]
    assert item["goal_days"] == item["goal_data_days"] == 5
    assert item["average"] != item["goal_actual_average"] == "265.00"
    assert item["percent_of_goal"] == result["goals"][0]["percent"] == "100.00"
    row = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id == user, DailyNutrition.date == date(2026, 10, 7)))
    row.nutrition_summary_json = {"carbohydrate_total": {"state": "partial", "value": "265", "coverage": "50"}}
    db.session.commit()
    result = DashboardSummaryService().build(user, period(), "kg")
    item = result["summary"]["nutrition"]["averages"]["total_carbs"]
    assert item["days"] == 6 and item["goal_data_days"] == 4
    assert item["percent_of_goal"] is None and result["goals"][0]["percent"] is None
    points = health_progress(user, date(2026, 10, 1), date(2026, 10, 7), "UTC")["points"]
    assert points[-1]["carbohydrate_g"] is None
    before = DashboardSummaryService().build(user, period("2026-09-01", "2026-09-30"), "kg")
    assert not before["goals"]


@pytest.mark.parametrize("total,net,partial,recorded", [(300, 200, False, 7), (None, 300, False, 0), (300, 200, True, 0)])
def test_adherence_nutrition_describes_coverage_not_excess(app, user, total, net, partial, recorded):
    goal(user)
    for offset in range(7):
        db.session.add(DailyNutrition(user_id=user, date=date(2026, 10, 1)+timedelta(days=offset), source="manual",
            total_carbs_g=total, net_carbs_g=net,
            nutrition_summary_json={"carbohydrate_total": {"state": "partial"}} if partial else None))
    db.session.commit()
    item = adherence_summary(db.session.get(User, user), days=7, end=date(2026, 10, 7))["items"][0]
    assert item["completed"] == recorded and item["expected"] == 7
    assert item["details"]["field"] == "total_carbs_g"
    assert item["details"]["registered_percent_of_target"] == (113.21 if recorded else None)
    assert "registro completo" in item["summary"]


def test_real_catalog_recipe_snapshot_projection_preserves_unknown_nets(app, user):
    from tests.test_nutrition_intelligence import food
    app.config["NUTRITION_INTELLIGENCE_ENABLED"] = True
    f = food()
    f["nutrients"].update({"carbohydrate_total": {"state": "known", "value": "30", "unit": "g"},
                            "fiber": {"state": "known", "value": "5", "unit": "g"}})
    food_catalog.stage({"schema_version": "2.0", "source": f["source"], "revision": "1", "license": "QA fictitious", "foods": [f]})
    food_catalog.activate(f["source"], "1", 1)
    ref = food_catalog.search(user)[0]["ref"]
    draft = ni.create_draft(user, target="2026-10-01", entries=[{"ref": ref, "amount": "100", "unit": "g"}])
    draft = ni.mutate_draft(user, draft.public_id, draft.revision, "accept", {"index": 0})
    recipe = ni.save_template(user, draft.public_id, draft.revision)
    snapshot = copy.deepcopy(draft.snapshot_json)
    recipe_snapshot = copy.deepcopy(recipe.nutrition_snapshot_json)
    log, _ = ni.confirm(user, ni.confirmation_token(draft))
    db.session.commit()
    day = ni.daily_summary(user, date(2026, 10, 1))["day"]
    assert day.total_carbs_g == 30 and day.net_carbs_g is None
    assert day.nutrition_summary_json["carbohydrate_total"]["state"] == "complete"
    assert day.nutrition_summary_json["net_carbs"]["state"] == "unknown"
    DashboardSummaryService().build(user, period(), "kg")
    assert log.snapshot_json == snapshot
    assert recipe.nutrition_snapshot_json == recipe_snapshot
    incompatible = copy.deepcopy(f)
    incompatible.update(basis_amount="250", basis_unit="ml", density_g_ml=None)
    incompatible["nutrients"] = {"fiber": {"state": "known", "value": "5", "unit": "g"}}
    summary = summarize([ingredient(f, 100, "g"), ingredient(incompatible, 250, "ml")])
    assert summary["carbohydrate_total"]["state"] == "partial"
    assert summary["net_carbs"]["state"] == "unknown"


def test_demo_seven_real_goals_idempotent_owner_only(app, demo, user):
    first = seed_demo_goals(confirmed=True)
    db.session.commit()
    assert len(first["created"]) == 7 and not first["conflicts"]
    second = seed_demo_goals(confirmed=True)
    db.session.commit()
    assert not second["created"] and len(second["reused"]) == 7
    rows = db.session.scalars(db.select(UserGoal).where(UserGoal.user_id == demo)).all()
    assert {r.goal_type for r in rows} == {s[0] for s in SPECS}
    assert all(r.start_date == date(2026, 10, 1) and r.source == "demo_goals_v1" for r in rows)
    assert not db.session.scalar(db.select(UserGoal.id).where(UserGoal.user_id == user))


@pytest.mark.parametrize("edit", ["target", "paused", "archived", "manual", "collision"])
def test_demo_preserves_edited_manual_goals_and_collisions(app, demo, user, edit):
    if edit in {"manual", "collision"}:
        row = goal(demo if edit == "manual" else user)
        if edit == "collision":
            from app.services.demo_goals import goal_id
            row.public_id = goal_id("nutrition_carbohydrates")
    else:
        seed_demo_goals(confirmed=True)
        row = db.session.scalar(db.select(UserGoal).where(UserGoal.user_id == demo, UserGoal.goal_type == "nutrition_carbohydrates"))
        changes = {"target_value": 280} if edit == "target" else {"state": edit}
        patch_goal(demo, row.public_id, {"base_revision": row.revision, **changes})
    db.session.commit()
    before = (row.target_value, row.state, row.revision, row.source)
    report = seed_demo_goals(confirmed=True)
    db.session.commit()
    assert report["conflicts"] == ["nutrition_carbohydrates"]
    assert before == (row.target_value, row.state, row.revision, row.source)


def test_demo_guard_and_cli_rollback(app, demo, monkeypatch):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["seed-demo-goals"]).exit_code != 0
    app.config["DEMO_GOALS_ENVIRONMENT"] = "production"
    assert runner.invoke(args=["seed-demo-goals", "--confirm"]).exit_code != 0
    import app.services.demo_goals as service
    original = service.create_goal
    def fail(owner, payload):
        if payload["goal_type"] == "nutrition_fat":
            raise RuntimeError("Fictitious QA failure; must never be echoed")
        return original(owner, payload)
    monkeypatch.setattr(service, "create_goal", fail)
    result = runner.invoke(args=["seed-demo-goals", "--confirm", "--confirm-production"])
    assert result.exit_code != 0 and "QA failure" not in result.output
    assert db.session.query(UserGoal).count() == 0
    monkeypatch.setattr(service, "create_goal", original)
    assert runner.invoke(args=["seed-demo-goals", "--confirm", "--confirm-production"]).exit_code == 0


def test_demo_identity_required(app, user):
    app.config.update(DEMO_GOALS_ENABLED=True, DEMO_GOALS_ENVIRONMENT="test")
    with pytest.raises(ValueError, match="identidad"):
        seed_demo_goals(confirmed=True)
    assert not db.session.query(UserGoal).count()


@pytest.mark.parametrize("total,net", [("30", "23"), (None, "23"), ("30", None)])
def test_explicit_source_nets_are_independent_and_never_invented(total, net):
    from tests.test_nutrition_intelligence import food
    f = food()
    for key, value in (("carbohydrate_total", total), ("net_carbs", net), ("fiber", "5")):
        if value is not None:
            f["nutrients"][key] = {"state": "known", "value": value, "unit": "g"}
    summary = summarize([ingredient(f, 100, "g")])
    for key, value in (("carbohydrate_total", total), ("net_carbs", net)):
        assert summary[key]["state"] == ("complete" if value is not None else "unknown")
        assert summary[key]["value"] == value


def test_nutrition_coach_ratio_is_neutral_above_and_below_target(app, user):
    from app.services.coach import CoachBriefService
    goal(user)
    for offset in range(7):
        db.session.add(DailyNutrition(user_id=user, date=date(2026, 10, 1)+timedelta(days=offset),
                                     source="manual", total_carbs_g=300))
    db.session.commit()
    for value in (300, 150):
        for row in db.session.scalars(db.select(DailyNutrition).where(DailyNutrition.user_id == user)):
            row.total_carbs_g = value
        db.session.commit()
        brief = CoachBriefService().build(db.session.get(User, user), today=date(2026, 10, 7))
        item = next(i for i in brief["week"]["signals"] if i["metric"] == "nutrition_carbohydrates")
        assert item["type"] == "recorded" and item["severity"] == "low"
        assert "registrado respecto al objetivo" in item["title"]
        assert "No evalúa cumplimiento nutricional" in item["message"]


@pytest.mark.parametrize("frequency_period,target", [("weekly", 7), ("daily", 1)])
def test_weight_and_strength_frequency_only_use_applicable_dates(app, user, frequency_period, target):
    from tests.test_dashboard_trends import _plan, _session
    plan, version = _plan(user)
    create_goal(user, {"goal_type": "weight_logging_frequency", "target_value": target, "unit": "log",
                       "period": frequency_period, "timezone": "UTC", "start_date": "2026-10-05"})
    create_goal(user, {"goal_type": "training_sessions_per_week", "target_value": 3, "unit": "session",
                       "period": "weekly", "timezone": "UTC", "start_date": "2026-10-05"})
    for day in (1, 5, 6, 7):
        at = datetime(2026, 10, day, 12, tzinfo=timezone.utc)
        db.session.add(WeighIn(user_id=user, recorded_at=at, weight_kg=77, source="manual"))
        _session(user, plan, version, at)
    # A second measurement on the same day is not another recorded day.
    db.session.add(WeighIn(user_id=user, recorded_at=datetime(2026, 10, 7, 18, tzinfo=timezone.utc), weight_kg=77, source="manual"))
    db.session.commit()
    goals = {g["type"]: g for g in DashboardSummaryService().build(user, period(), "kg")["goals"]}
    weight = goals["weight_logging_frequency"]
    assert weight["actual"] == ("7.00" if frequency_period == "weekly" else "1.00")
    assert weight["data_days"] == weight["applicable_days"] == 3
    assert weight["percent"] == "100.00"
    strength = goals["training_sessions_per_week"]
    assert strength["actual"] == "7.00" and strength["applicable_days"] == 3
    assert strength["percent"] == "233.33"
