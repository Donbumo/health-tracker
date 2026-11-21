"""Synthetic body backfill over the existing DEMO; no production connections."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, TrainingSession, TrainingSet, User, WeighIn
from app.services import demo_seed
from app.services.demo_fixtures import (DEMO_BODY_NOTE, DEMO_BODY_SOURCE, DEMO_HEIGHT_M,
                                      DEMO_PUBLIC_ID, body_document, identity)
from app.services.dashboard import DashboardDateRange, DashboardSummaryService
from app.services.dashboard.weight import WeightTrendService
from app.services.exporters.weigh_in import build_weigh_in_document
from app.services.importers.weigh_in import persist_weigh_in_document, WeighInImportError
from app.services.validation import validate_json_document
from app.services.weight_history import weight_history
from tests.conftest import DEMO_TEST_PASSWORD, login

AS_OF = date(2026, 11, 18)
ANCHOR = date(2026, 10, 1)


def account():
    return db.session.scalar(db.select(User).where(User.public_id == DEMO_PUBLIC_ID))


def weights(user_id):
    return db.session.scalars(db.select(WeighIn).where(WeighIn.user_id == user_id).order_by(WeighIn.recorded_at)).all()


def preserved(user_id):
    # Entire synthetic owner state, including credentials, timestamps and child
    # tables. Only the explicitly requested WeighIn domain is excluded.
    state = {}
    for table in db.metadata.sorted_tables:
        if table.name == "weigh_ins":
            continue
        if table.name == "users":
            query = table.select().where(table.c.id == user_id)
        elif "user_id" in table.c:
            query = table.select().where(table.c.user_id == user_id)
        else:
            continue
        state[table.name] = copy.deepcopy([tuple(row) for row in db.session.execute(query.order_by(*table.primary_key.columns))])
    return state


def legacy_demo(app):
    with patch.object(demo_seed, "_body_history"):
        result = app.test_cli_runner().invoke(args=["seed", "demo", "--as-of", AS_OF.isoformat(), "--confirm-local"])
    assert result.exit_code == 0, result.output
    return account()


def body_seed(app, as_of=AS_OF):
    return app.test_cli_runner().invoke(args=["seed", "demo", "--body-only", "--as-of", as_of.isoformat(), "--confirm-local"])


@pytest.mark.parametrize("zone_name", ["America/Mexico_City", "America/New_York"])
def test_body_profile_frequency_units_timezones_and_fluctuations(demo_enabled, zone_name):
    demo_enabled.config["APP_TIMEZONE"] = zone_name
    user = legacy_demo(demo_enabled)
    result = body_seed(demo_enabled)
    assert result.exit_code == 0, result.output
    assert "weigh_ins=49" in result.output and "body_measurements=21" in result.output
    records = weights(user.id)
    assert len(records) == len({r.recorded_at.date() for r in records}) == 49
    composition = [r for r in records if r.body_fat_percentage is not None]
    assert len(composition) == 21
    zone = ZoneInfo(zone_name)
    for row in records:
        timestamp = row.recorded_at.replace(tzinfo=timezone.utc) if row.recorded_at.tzinfo is None else row.recorded_at
        local = timestamp.astimezone(zone)
        assert ANCHOR <= local.date() <= AS_OF and local.hour == 7 and local.minute == 0
        assert row.public_id == row.client_event_id == identity("weigh-in/" + local.date().isoformat())
        assert row.source == DEMO_BODY_SOURCE and row.notes == DEMO_BODY_NOTE
        assert row.raw_payload_json == body_document(user.id, local.date(), ANCHOR, zone_name)
        validate_json_document(build_weigh_in_document(row, user.id), "weigh_in")
        fields = (row.body_fat_percentage, row.muscle_mass_kg, row.water_percentage, row.visceral_fat, row.bmi, row.bmr_kcal)
        if local.weekday() in {1, 3, 5}:
            assert all(v is not None for v in fields)
            assert 22 < row.body_fat_percentage < 24
            assert 56.7 < row.muscle_mass_kg < 57.2 and 55 < row.water_percentage < 56
            assert Decimal("7.7") < row.visceral_fat < Decimal("8.1")
            assert abs(row.bmi - row.weight_kg / DEMO_HEIGHT_M ** 2) <= Decimal(".0005")
            assert row.bmr_kcal == (1700 + 10 * (row.weight_kg - 75)).quantize(Decimal(".01"))
        else:
            assert all(v is None for v in fields)
    assert abs(records[0].weight_kg - Decimal("78.4")) < Decimal(".1")
    assert abs(records[-1].weight_kg - Decimal("77.2")) < Decimal(".15")
    deltas = [b.weight_kg - a.weight_kg for a, b in zip(records, records[1:])]
    assert min(deltas) < 0 < max(deltas) and max(abs(v) for v in deltas) < Decimal(".4")
    for index in range(43):
        assert sum(row.body_fat_percentage is not None for row in records[index:index + 7]) == 3
    assert abs(composition[0].body_fat_percentage - Decimal("23.4")) < Decimal(".1")
    assert abs(composition[-1].body_fat_percentage - Decimal("22.8")) < Decimal(".1")
    for field, limit in (("body_fat_percentage", ".15"), ("muscle_mass_kg", ".08"),
                         ("water_percentage", ".15"), ("visceral_fat", ".07")):
        assert max(abs(getattr(b, field) - getattr(a, field)) for a, b in zip(composition, composition[1:])) < Decimal(limit)


def test_backfill_preserves_every_previous_module_password_and_other_owner(demo_enabled, user):
    demo = legacy_demo(demo_enabled)
    sentinel = WeighIn(user_id=user, recorded_at=datetime(2026, 10, 15, 13), weight_kg=Decimal("99.1"), source="manual")
    db.session.add(sentinel)
    db.session.commit()
    before = preserved(demo.id)
    other = (sentinel.id, sentinel.weight_kg, sentinel.updated_at, preserved(user))
    assert not weights(demo.id)
    # Prove no nutrition/energy/session path can be invoked during body-only.
    with patch.object(demo_seed, "_recipes", side_effect=AssertionError("unrelated recipes")), \
            patch.object(demo_seed, "_nutrition_day", side_effect=AssertionError("unrelated nutrition")), \
            patch.object(demo_seed, "_energy_day", side_effect=AssertionError("unrelated energy")), \
            patch.object(demo_seed, "_session", side_effect=AssertionError("unrelated strength")):
        result = body_seed(demo_enabled)
    assert result.exit_code == 0, result.output
    assert before == preserved(demo.id)
    assert other == (sentinel.id, sentinel.weight_kg, sentinel.updated_at, preserved(user))
    assert len(weights(demo.id)) == 49 and len(weights(user)) == 1
    assert demo.check_password(DEMO_TEST_PASSWORD)
    counts = {model: db.session.scalar(db.select(db.func.count()).select_from(model).where(model.user_id == demo.id))
              for model in (DailyNutrition, DailyEnergy, TrainingSession, TrainingSet)}
    assert list(counts.values()) == [49, 49, 21, 378]
    original = [(r.id, r.public_id, r.updated_at, r.raw_payload_json) for r in weights(demo.id)]
    replay = body_seed(demo_enabled)
    assert replay.exit_code == 0 and "Registros creados en esta ejecución: 0" in replay.output
    assert original == [(r.id, r.public_id, r.updated_at, r.raw_payload_json) for r in weights(demo.id)]
    assert before == preserved(demo.id)


def test_body_extension_adds_only_missing_days_without_moving_the_profile(demo_enabled, demo_account):
    demo = account()
    original = [(r.id, r.updated_at, r.raw_payload_json) for r in weights(demo.id)]
    before = preserved(demo.id)
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 12, 2, 20, tzinfo=tz)
    with patch.object(demo_seed, "datetime", Later):
        result = body_seed(demo_enabled, date(2026, 12, 2))
    assert result.exit_code == 0, result.output
    assert "weigh_ins=14" in result.output and "body_measurements=6" in result.output
    assert len(weights(demo.id)) == 63
    assert original == [(r.id, r.updated_at, r.raw_payload_json) for r in weights(demo.id)[:49]]
    assert before == preserved(demo.id)


@pytest.mark.parametrize("source", ["manual", DEMO_BODY_SOURCE])
def test_manual_or_unmarked_same_day_never_overwritten_and_batch_rolls_back(demo_enabled, source):
    demo = legacy_demo(demo_enabled)
    sentinel = WeighIn(user_id=demo.id, recorded_at=datetime(2026, 10, 15, 21), weight_kg=Decimal("82.1"), source=source, notes="Synthetic manual QA")
    db.session.add(sentinel)
    db.session.commit()
    before = preserved(demo.id)
    result = body_seed(demo_enabled)
    assert result.exit_code != 0
    records = weights(demo.id)
    assert len(records) == 1 and records[0].weight_kg == Decimal("82.1")
    assert before == preserved(demo.id)


@pytest.mark.parametrize("field,value", [("weight_kg", Decimal("85")), ("recorded_at", datetime(2026, 10, 1, 20))])
def test_edited_demo_values_or_timestamp_never_overwritten(demo_enabled, demo_account, field, value):
    row = weights(account().id)[0]
    setattr(row, field, value)
    db.session.commit()
    original = [(r.id, r.updated_at, r.weight_kg, r.recorded_at) for r in weights(account().id)]
    result = body_seed(demo_enabled)
    assert result.exit_code != 0
    assert original == [(r.id, r.updated_at, r.weight_kg, r.recorded_at) for r in weights(account().id)]


def test_late_importer_failure_rolls_back_body_backfill(demo_enabled):
    from app.services.importers import weigh_in
    demo = legacy_demo(demo_enabled)
    before = preserved(demo.id)
    real = weigh_in.persist_weigh_in_document
    def fail(document, *args, **kwargs):
        result = real(document, *args, **kwargs)
        if document["data"]["recorded_at"].startswith("2026-10-28"):
            raise RuntimeError("Synthetic late QA failure")
        return result
    with patch.object(weigh_in, "persist_weigh_in_document", fail):
        result = body_seed(demo_enabled)
    assert result.exit_code != 0 and not weights(demo.id)
    assert before == preserved(demo.id)


def test_body_only_requires_existing_demo_and_never_changes_credentials(demo_enabled, monkeypatch):
    assert body_seed(demo_enabled).exit_code != 0
    assert not db.session.scalar(db.select(User.id))
    demo = legacy_demo(demo_enabled)
    before = preserved(demo.id)
    monkeypatch.setenv("DEMO_USER_PASSWORD", "incorrect-fictional-body-password")
    assert body_seed(demo_enabled).exit_code != 0
    assert before == preserved(demo.id) and not weights(demo.id)


def test_body_only_does_not_require_nutrition_flag(demo_enabled):
    demo = legacy_demo(demo_enabled)
    demo_enabled.config["NUTRITION_INTELLIGENCE_ENABLED"] = False
    result = body_seed(demo_enabled)
    assert result.exit_code == 0 and len(weights(demo.id)) == 49


def test_real_weight_dashboard_month_comparison_and_owner_only_routes(demo_enabled, client, user, demo_account):
    demo = account()
    period = DashboardDateRange.from_query({"from": "2026-10-01", "to": "2026-11-18"}, "UTC")
    report = WeightTrendService().build(demo.id, period, "kg")
    records = weights(demo.id)
    assert report["summary"]["entries"] == report["coverage"]["weight_entries"] == 49
    assert report["summary"]["latest"] == records[-1].weight_kg
    assert report["summary"]["change"] == records[-1].weight_kg - records[0].weight_kg
    expected = (sum(r.weight_kg for r in records[-7:]) / 7).quantize(Decimal(".001"))
    assert report["summary"]["moving_average_7d"] == expected
    assert {m["key"] for m in report["body"]["metrics"]} == {"body_fat", "muscle_mass", "water", "visceral_fat", "bmi"}
    assert all(m["entries"] == 21 for m in report["body"]["metrics"])
    assert all(m["unit"] == "kg" for m in report["body"]["metrics"] if m["key"] == "muscle_mass")
    assert weight_history(demo.id)["average_last_seven"].quantize(Decimal(".001")) == expected
    november = DashboardDateRange.from_query({"from": "2026-11-01", "to": "2026-11-18", "compare": "month-to-date"}, "UTC")
    dashboard = DashboardSummaryService().build(demo.id, november, "kg")
    assert dashboard["summary"]["weight"]["entries"] == 18
    assert dashboard["previous_period"]["summary"]["weight"]["entries"] == 18
    assert dashboard["previous_period"]["range"]["from"] == "2026-10-01"
    assert WeightTrendService().build(user, period, "kg")["summary"]["entries"] == 0
    row_id = records[0].id
    assert login(client, "demo@healthtracker.test", DEMO_TEST_PASSWORD).status_code == 302
    for route in ("/dashboard?from=2026-10-01&to=2026-11-18", "/weigh-ins", "/weigh-ins/history", f"/weigh-ins/{row_id}", f"/weigh-ins/{row_id}/export/json"):
        assert client.get(route).status_code == 200, route
    client.post("/logout")
    login(client)
    assert client.get(f"/weigh-ins/{row_id}").status_code == 404


def test_canonical_persistence_validates_effective_owner_and_utc(demo_enabled, user):
    document = body_document(user + 1, ANCHOR, ANCHOR, "America/Mexico_City")
    with pytest.raises(WeighInImportError):
        persist_weigh_in_document(document, user)
    document["user_id"] = user
    document["data"]["recorded_at"] = "2026-10-01T07:00:00-06:00"
    record, duplicate = persist_weigh_in_document(document, user)
    assert not duplicate and record.recorded_at.hour == 13
    assert record.recorded_at.utcoffset() == timedelta(0)
