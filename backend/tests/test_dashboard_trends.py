import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from sqlalchemy import event, text

from app import create_app
from app.extensions import db
from app.models import (
    Activity,
    DailyEnergy,
    DailyNutrition,
    PlannedWorkout,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
    UserGoal,
    WeighIn,
)
from app.services.dashboard import (
    DashboardDateRange,
    DashboardRangeError,
    DashboardSummaryService,
)
from tests.conftest import login


def _range(query=None, *, today=date(2026, 8, 2), timezone_name="UTC"):
    return DashboardDateRange.from_query(query or {}, timezone_name, today=today)


@pytest.mark.parametrize(
    ("preset", "expected_start", "expected_end", "days"),
    (
        ("today", date(2026, 8, 2), date(2026, 8, 2), 1),
        ("7d", date(2026, 7, 27), date(2026, 8, 2), 7),
        ("30d", date(2026, 7, 4), date(2026, 8, 2), 30),
        ("90d", date(2026, 5, 5), date(2026, 8, 2), 90),
        ("this-month", date(2026, 8, 1), date(2026, 8, 2), 2),
        ("previous-month", date(2026, 7, 1), date(2026, 7, 31), 31),
        ("this-year", date(2026, 1, 1), date(2026, 8, 2), 214),
    ),
)
def test_dashboard_date_range_presets(preset, expected_start, expected_end, days):
    result = _range({"preset": preset})
    assert result.start_date == expected_start
    assert result.end_date == expected_end
    assert result.days == days


@pytest.mark.parametrize("period", ("7", "30", "90"))
def test_dashboard_period_query_uses_reproducible_global_ranges(period):
    result = _range({"period": period})
    assert result.preset == f"{period}d"
    assert result.days == int(period)


def test_dashboard_default_period_is_seven_days():
    assert _range().preset == "7d"
    assert _range().days == 7


def test_dashboard_custom_range_and_previous_period_are_inclusive():
    result = _range(
        {"from": "2026-06-01", "to": "2026-06-30", "compare": "previous"}
    )
    assert result.preset == "custom"
    assert result.days == 30
    assert result.previous_start == date(2026, 5, 2)
    assert result.previous_end == date(2026, 5, 31)
    assert result.as_dict()["previous_label"]


@pytest.mark.parametrize(
    ("query", "message"),
    (
        ({"preset": "forever"}, "periodo"),
        ({"from": "2026-06-01"}, "dos fechas"),
        ({"from": "2026-06-30", "to": "2026-06-01"}, "posterior"),
        ({"from": "2025-01-01", "to": "2026-06-01"}, "366"),
        ({"from": "not-a-date", "to": "2026-06-01"}, "AAAA-MM-DD"),
        ({"preset": "30d", "compare": "other"}, "comparación"),
    ),
)
def test_dashboard_date_range_rejects_human_readable_invalid_values(query, message):
    with pytest.raises(DashboardRangeError, match=message):
        _range(query)


def test_dashboard_date_range_uses_dst_safe_utc_boundaries():
    result = _range(
        {"preset": "today"},
        today=date(2026, 3, 8),
        timezone_name="America/New_York",
    )
    start, end = result.utc_bounds()
    assert start == datetime(2026, 3, 8, 5, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 9, 4, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 23 * 3600


def test_dashboard_date_range_uses_dst_fallback_boundaries():
    result = _range(
        {"preset": "today"},
        today=date(2026, 11, 1),
        timezone_name="America/New_York",
    )
    start, end = result.utc_bounds()
    assert start == datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 2, 5, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 25 * 3600


def _plan(user_id: int):
    plan = TrainingPlan(user_id=user_id, name="Plan longitudinal ficticio")
    db.session.add(plan)
    db.session.flush()
    version = TrainingPlanVersion(
        user_id=user_id,
        training_plan_id=plan.id,
        version_number=1,
        created_by_user_id=user_id,
        schema_version="1.0",
        sha256=f"{user_id:064x}",
        content={
            "schema_version": "1.0",
            "record_type": "training_plan",
            "user_id": user_id,
            "source_type": "manual_generated",
            "data": {"name": "Plan longitudinal ficticio", "weeks": []},
        },
    )
    db.session.add(version)
    db.session.flush()
    return plan, version


def _session(user_id: int, plan, version, performed_at, *, load_mode="direct_total"):
    record = TrainingSession(
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        performed_at=performed_at,
        planned_week_number=1,
        planned_day_number=1,
        duration_seconds=3600,
        calories_burned=Decimal("250"),
    )
    db.session.add(record)
    db.session.flush()
    exercise = TrainingSessionExercise(
        user_id=user_id,
        training_session_id=record.id,
        exercise_order=1,
        planned_exercise_order=1,
        name="Ejercicio longitudinal ficticio",
    )
    db.session.add(exercise)
    db.session.flush()
    db.session.add(
        TrainingSet(
            user_id=user_id,
            training_session_exercise_id=exercise.id,
            set_number=1,
            planned_set_number=1,
            weight_kg=Decimal("50"),
            reps=10,
            load_details_json={"load_mode": load_mode},
        )
    )
    return record


def _seed_summary_period(user_id: int):
    db.session.add_all(
        [
            DailyNutrition(
                user_id=user_id,
                date=date(2026, 7, 1),
                source="qa_fixture",
                calories=Decimal("1000"),
                protein_g=Decimal("50"),
                fat_g=Decimal("40"),
                net_carbs_g=Decimal("90"),
                fiber_g=Decimal("20"),
            ),
            DailyNutrition(
                user_id=user_id,
                date=date(2026, 7, 2),
                source="qa_fixture",
                calories=Decimal("1100"),
                protein_g=Decimal("60"),
                fat_g=Decimal("45"),
                net_carbs_g=Decimal("95"),
                fiber_g=Decimal("22"),
            ),
            DailyEnergy(
                user_id=user_id,
                date=date(2026, 7, 1),
                source="device_qa",
                total_calories=Decimal("900"),
                active_calories=Decimal("300"),
                steps=8000,
                distance_meters=Decimal("6000"),
            ),
            DailyEnergy(
                user_id=user_id,
                date=date(2026, 7, 1),
                source="manual",
                total_calories=Decimal("800"),
            ),
            DailyEnergy(
                user_id=user_id,
                date=date(2026, 7, 2),
                source="device_qa",
                total_calories=Decimal("1000"),
                active_calories=Decimal("350"),
                steps=9000,
                distance_meters=Decimal("7000"),
            ),
            UserGoal(
                user_id=user_id,
                goal_type="nutrition_protein",
                target_value=Decimal("55"),
                unit="g",
                period="daily",
                applicable_days_json=[],
                timezone="UTC",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 7),
                state="active",
                source="qa_fixture",
            ),
            UserGoal(
                user_id=user_id,
                goal_type="daily_steps",
                target_value=Decimal("8500"),
                unit="step",
                period="daily",
                applicable_days_json=[],
                timezone="UTC",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 7),
                state="active",
                source="qa_fixture",
            ),
            UserGoal(
                user_id=user_id,
                goal_type="nutrition_calories",
                target_value=Decimal("2000"),
                unit="kcal",
                period="daily",
                applicable_days_json=[],
                timezone="UTC",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 7),
                state="active",
                source="qa_fixture",
            ),
            WeighIn(
                user_id=user_id,
                recorded_at=datetime(2026, 7, 1, 7, tzinfo=timezone.utc),
                weight_kg=Decimal("70"),
                body_fat_percentage=Decimal("18"),
                muscle_mass_kg=Decimal("55"),
                source="qa_fixture",
            ),
            WeighIn(
                user_id=user_id,
                recorded_at=datetime(2026, 7, 7, 7, tzinfo=timezone.utc),
                weight_kg=Decimal("69.5"),
                body_fat_percentage=Decimal("17.5"),
                muscle_mass_kg=Decimal("55.5"),
                source="qa_fixture",
            ),
        ]
    )
    plan, version = _plan(user_id)
    planned = PlannedWorkout(
        user_id=user_id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        scheduled_for_date=date(2026, 7, 2),
        timezone="UTC",
        status="completed",
        title_snapshot="Plan completado ficticio",
        payload_snapshot_json={"name": "Plan completado ficticio", "exercises": []},
        source_version=1,
    )
    db.session.add(planned)
    db.session.flush()
    session = _session(
        user_id,
        plan,
        version,
        datetime(2026, 7, 2, 18, tzinfo=timezone.utc),
    )
    session.planned_workout_id = planned.id
    db.session.commit()


def test_dashboard_summary_contract_preserves_decimal_nulls_units_and_coverage(app, user):
    with app.app_context():
        _seed_summary_period(user)
        result = DashboardSummaryService().build(
            user,
            _range({"from": "2026-07-01", "to": "2026-07-07"}),
            "lb",
        )

    assert result["range"] == {
        "preset": "custom",
        "from": "2026-07-01",
        "to": "2026-07-07",
        "timezone": "UTC",
        "days": 7,
        "label": "1 jul 2026 – 7 jul 2026",
        "compare": None,
        "previous_from": None,
        "previous_to": None,
        "previous_label": None,
    }
    assert result["summary"]["energy"]["consumed_total"] == "2100.000"
    assert result["summary"]["energy"]["expended_total"] == "1800.00"
    assert result["summary"]["energy"]["balance_total"] == "300.000"
    assert result["trends"]["energy"][1]["consumed_rolling_7d"] == "1050.00"
    assert result["trends"]["energy"][1]["expended_rolling_7d"] == "900.00"
    assert result["summary"]["nutrition"]["averages"]["fat"]["average"] == "42.50"
    assert result["summary"]["nutrition"]["averages"]["net_carbs"]["average"] == "92.50"
    assert result["summary"]["protein"]["goal_total"] == "385.000"
    assert result["summary"]["protein"]["balance"] == "0.000"
    assert result["summary"]["protein"]["days_at_goal"] == 1
    assert result["summary"]["weight"]["unit"] == "lb"
    assert result["summary"]["weight"]["entries"] == 2
    assert result["summary"]["weight"]["moving_average_7d"] is not None
    assert result["summary"]["body"]["default_metric"] == "body_fat"
    assert result["summary"]["body"]["metrics"][0]["change"] == "-0.500"
    assert result["summary"]["activity"]["steps_total"] == 17000
    assert result["summary"]["activity"]["days_at_goal"] == 1
    assert result["summary"]["activity"]["distance_km"] == "13.00"
    assert result["summary"]["training"]["sessions"] == 1
    assert result["summary"]["training"]["adherence_percent"] == "100.00"
    assert result["summary"]["training"]["volume_supported"] is True
    assert result["summary"]["training"]["volume"] == "1102.31"
    assert result["summary"]["training"]["calories"] == "250.00"
    assert result["trends"]["energy"][2]["consumed"] is None
    assert result["coverage"]["nutrition_days"] == 2
    assert result["coverage"]["energy_days"] == 2
    assert result["coverage"]["weight_entries"] == 2
    assert result["coverage"]["steps_days"] == 2
    assert {goal["type"] for goal in result["goals"]} >= {
        "daily_steps", "nutrition_calories", "nutrition_protein"
    }
    assert 3 <= len(result["insights"]) <= 5
    json.dumps(result)


def test_dashboard_summary_is_owner_only_and_does_not_turn_absence_into_zero(app, user):
    with app.app_context():
        _seed_summary_period(user)
        second = User(username="dashboard-trends-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        result = DashboardSummaryService().build(
            second.id,
            _range({"from": "2026-07-01", "to": "2026-07-07"}),
            "kg",
        )
    assert result["summary"]["energy"]["consumed_total"] is None
    assert result["summary"]["protein"]["total"] is None
    assert result["summary"]["weight"]["latest"] is None
    assert result["summary"]["activity"]["steps_total"] is None
    assert result["summary"]["training"]["sessions"] == 0
    assert result["goals"] == []
    assert all(point["consumed"] is None for point in result["trends"]["energy"])


def test_dashboard_energy_uses_available_expenditure_when_manual_row_is_partial(app, user):
    with app.app_context():
        db.session.add_all(
            [
                DailyNutrition(
                    user_id=user,
                    date=date(2026, 7, 1),
                    source="qa_fixture",
                    calories=Decimal("1000"),
                ),
                DailyNutrition(
                    user_id=user,
                    date=date(2026, 7, 2),
                    source="qa_fixture",
                    calories=Decimal("900"),
                ),
                DailyEnergy(
                    user_id=user,
                    date=date(2026, 7, 1),
                    source="device_qa",
                    total_calories=Decimal("1800"),
                ),
                DailyEnergy(
                    user_id=user,
                    date=date(2026, 7, 1),
                    source="manual",
                    steps=7000,
                ),
            ]
        )
        db.session.commit()
        result = DashboardSummaryService().build(
            user,
            _range({"from": "2026-07-01", "to": "2026-07-02"}),
            "kg",
        )

    assert result["summary"]["energy"]["expended_total"] == "1800.00"
    assert result["summary"]["energy"]["balance_total"] == "-800.000"
    assert result["trends"]["energy"][0]["source"] == "device_qa"
    assert result["trends"]["energy"][0]["expenditure_source"] == "Dispositivo"
    assert result["trends"]["activity"][0]["steps"] == 7000
    assert result["trends"]["activity"][0]["sources"] == ["Manual"]
    assert result["trends"]["energy"][1]["expended"] is None
    assert result["trends"]["energy"][1]["balance"] is None


def test_dashboard_training_volume_is_unsupported_for_non_comparable_modes(app, user):
    with app.app_context():
        plan, version = _plan(user)
        _session(
            user,
            plan,
            version,
            datetime(2026, 7, 2, 18, tzinfo=timezone.utc),
            load_mode="duration_distance",
        )
        db.session.commit()
        result = DashboardSummaryService().build(
            user,
            _range({"from": "2026-07-01", "to": "2026-07-07"}),
            "kg",
        )
    assert result["summary"]["training"]["volume"] is None
    assert result["summary"]["training"]["volume_supported"] is False
    assert "no comparables" in result["summary"]["training"]["volume_reason"]


def test_dashboard_training_includes_imported_activity_without_mixing_strength_volume(app, user):
    with app.app_context():
        db.session.add(
            Activity(
                user_id=user,
                activity_type="cycling",
                discipline="cycling",
                started_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
                duration_seconds=1800,
                calories_kcal=Decimal("220"),
                source_type="uploaded",
                source_format="tcx",
                fingerprint_sha256="a" * 64,
                canonical_json={
                    "schema_version": "1.0",
                    "record_type": "activity",
                    "data": {"title": "Actividad QA ficticia"},
                },
                point_count=0,
                metrics_provenance_json={},
                status="imported",
            )
        )
        db.session.commit()
        result = DashboardSummaryService().build(
            user,
            _range({"from": "2026-07-01", "to": "2026-07-07"}),
            "kg",
        )
    assert result["summary"]["training"]["sessions"] == 1
    assert result["summary"]["training"]["activities"] == 1
    assert result["summary"]["training"]["strength_sessions"] == 0
    assert result["summary"]["training"]["duration_minutes"] == "30.00"
    assert result["summary"]["training"]["calories"] == "220.00"
    assert result["summary"]["training"]["volume"] is None
    assert result["summary"]["training"]["sources"] == ["Importación"]
    assert result["summary"]["training"]["distribution"][0]["label"] == "Cycling"


def test_dashboard_weight_change_requires_two_real_points(app, user):
    with app.app_context():
        db.session.add(
            WeighIn(
                user_id=user,
                recorded_at=datetime(2026, 7, 2, 7, tzinfo=timezone.utc),
                weight_kg=Decimal("70"),
                source="qa_fixture",
            )
        )
        db.session.commit()
        result = DashboardSummaryService().build(
            user,
            _range({"from": "2026-07-01", "to": "2026-07-07"}),
            "kg",
        )
    assert result["summary"]["weight"]["entries"] == 1
    assert result["summary"]["weight"]["change"] is None
    assert result["summary"]["weight"]["moving_average_7d"] is None


def test_dashboard_query_count_is_stable_across_range_lengths(app, user):
    with app.app_context():
        _seed_summary_period(user)

        def count_queries(date_range):
            statements = []

            def before_cursor_execute(*_args):
                statements.append(1)

            event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
            try:
                DashboardSummaryService().build(user, date_range, "kg")
            finally:
                event.remove(db.engine, "before_cursor_execute", before_cursor_execute)
            return len(statements)

        short_count = count_queries(
            _range({"from": "2026-07-01", "to": "2026-07-07"})
        )
        long_count = count_queries(
            _range({"from": "2025-08-03", "to": "2026-08-02"})
        )

    assert short_count == long_count
    assert short_count <= 10


def test_dashboard_comparison_has_equal_previous_range_and_safe_percentages(app, user):
    with app.app_context():
        db.session.add_all(
            [
                DailyNutrition(user_id=user, date=date(2026, 7, 1), source="qa", calories=0),
                DailyNutrition(user_id=user, date=date(2026, 7, 8), source="qa", calories=100),
            ]
        )
        db.session.commit()
        date_range = _range(
            {"from": "2026-07-08", "to": "2026-07-14", "compare": "previous"}
        )
        result = DashboardSummaryService().build(user, date_range, "kg")
    assert result["comparison"]["range"]["from"] == "2026-07-01"
    assert result["comparison"]["range"]["to"] == "2026-07-07"
    energy_row = next(
        row for row in result["comparison"]["rows"] if row["label"] == "Energía ingerida"
    )
    assert energy_row["absolute_change"] == "100.000"
    assert energy_row["relative_change_percent"] is None


def test_dashboard_and_today_routes_are_authenticated_canonical_and_private(client, user):
    assert client.get("/dashboard").status_code == 302
    assert client.get("/today").status_code == 302
    login(client)

    root = client.get("/")
    assert root.status_code == 200
    assert "Análisis longitudinal" in root.get_data(as_text=True)

    dashboard = client.get("/dashboard", query_string={"period": "30"})
    assert dashboard.status_code == 200
    assert dashboard.headers["Cache-Control"] == "private, no-store"
    html = dashboard.get_data(as_text=True)
    assert "Análisis longitudinal" in html
    assert "Anterior equivalente" in html
    assert 'id="dashboard-chart-data" type="application/json"' in html
    assert 'src="/static/js/dashboard_charts.js?v=dashboard-2-energy-controls"' in html
    assert 'href="/static/css/app.css?v=dashboard-2-energy-controls"' in html
    assert 'data-energy-chart-controls' in html
    for series_key in (
        "consumed",
        "expended",
        "balance",
        "consumed_rolling_7d",
        "expended_rolling_7d",
    ):
        assert f'data-energy-series-toggle="{series_key}"' in html
    for focus in ("all", "bars", "lines", "balance", "deficit", "surplus"):
        assert f'data-energy-focus="{focus}"' in html
    assert "cdn" not in html.lower()
    assert 'href="/today"' in html

    today_page = client.get("/today", query_string={"date": "2026-07-10"})
    assert today_page.status_code == 200
    assert today_page.headers["Cache-Control"] == "private, no-store"
    assert "Entrenamiento de hoy" in today_page.get_data(as_text=True)

    legacy = client.get("/dashboard", query_string={"date": "2026-07-10"})
    assert legacy.status_code == 302
    assert legacy.headers["Location"] == "/today?date=2026-07-10"


def test_dashboard_invalid_get_filters_return_human_error_not_500(client, user):
    login(client)
    response = client.get(
        "/dashboard", query_string={"from": "2026-08-02", "to": "2026-08-01"}
    )
    assert response.status_code == 400
    assert "fecha inicial no puede ser posterior" in response.get_data(as_text=True)
    assert "Se muestra el rango predeterminado" in response.get_data(as_text=True)

    invalid_period = client.get("/dashboard", query_string={"period": "365"})
    assert invalid_period.status_code == 400
    assert "periodo seleccionado no es válido" in invalid_period.get_data(as_text=True)


def test_dashboard_invalid_saved_timezone_returns_human_error_with_safe_fallback(app, client, user):
    with app.app_context():
        account = db.session.get(User, user)
        account.timezone = "Invalid/QA-Timezone"
        db.session.commit()

    login(client)
    response = client.get("/dashboard")
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "zona horaria guardada no es válida" in html
    assert "UTC" in html


def test_dashboard_ignores_client_user_id_and_keeps_owner_isolation(app, client, user):
    with app.app_context():
        second = User(username="dashboard-query-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.flush()
        db.session.add(
            DailyNutrition(
                user_id=second.id,
                date=date(2026, 8, 1),
                source="qa_fixture",
                calories=Decimal("9876"),
            )
        )
        db.session.commit()
        second_id = second.id

    login(client)
    response = client.get(
        "/dashboard",
        query_string={
            "from": "2026-08-01",
            "to": "2026-08-01",
            "user_id": second_id,
        },
    )
    assert response.status_code == 200
    assert "9876" not in response.get_data(as_text=True)


def test_dashboard_json_is_html_safe_and_tables_remain_as_accessible_fallback(app, client, user):
    with app.app_context():
        db.session.add(
            DailyEnergy(
                user_id=user,
                date=date(2026, 8, 1),
                source="</script><script>alert('qa')</script>",
                total_calories=Decimal("1200"),
            )
        )
        db.session.commit()
    login(client)
    response = client.get(
        "/dashboard", query_string={"from": "2026-08-01", "to": "2026-08-02"}
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "</script><script>alert" not in html
    assert "\\u003c/script\\u003e" in html
    assert html.count("<table>") >= 4
    assert "Los huecos representan datos ausentes" in html


def test_dashboard_chart_payload_keeps_previous_period_and_accessible_tables(app, client, user):
    with app.app_context():
        _seed_summary_period(user)
    login(client)
    response = client.get(
        "/dashboard",
        query_string={
            "from": "2026-07-08",
            "to": "2026-07-14",
            "compare": "previous",
        },
    )
    html = response.get_data(as_text=True)
    script = (
        Path(__file__).resolve().parents[1] / "app/static/js/dashboard_charts.js"
    ).read_text(encoding="utf-8")
    assert response.status_code == 200
    assert "Anterior" in html
    assert "comparison" in html
    assert 'name="start"' in html
    assert "consumed_rolling_7d" in script
    assert "chart-bar-balance-deficit" in script


def test_dashboard_chart_script_handles_invalid_shapes_and_resize_without_silent_catch():
    script = (
        Path(__file__).resolve().parents[1] / "app/static/js/dashboard_charts.js"
    ).read_text(encoding="utf-8")

    assert "Array.isArray(value)" in script
    assert "No se pudieron cargar los datos del gráfico." in script
    assert 'window.addEventListener("resize"' in script
    assert "window.requestAnimationFrame" in script
    assert "Math.max(300, Math.min(1180, measuredWidth))" in script
    assert 'node.addEventListener("click", reveal)' in script
    assert "catch (_error) {\n    return;" not in script


@pytest.mark.skipif(
    not Path("/.dockerenv").exists()
    and os.getenv("DASHBOARD_MARIADB_QA") != "1",
    reason="MariaDB dashboard integration runs only in Docker",
)
def test_mariadb_dashboard_service_and_indexed_range_query(app, tmp_path):
    mariadb_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "dashboard-mariadb-secret-key-long-enough",
            "API_TOKEN_SIGNING_KEY": "dashboard-mariadb-api-key-long-enough",
            "DATA_ROOT": tmp_path / "dashboard-mariadb",
            "SCHEMA_ROOT": app.config["SCHEMA_ROOT"],
            "APP_TIMEZONE": "UTC",
            "WTF_CSRF_ENABLED": False,
            "API_RATE_LIMIT_ENABLED": False,
        }
    )
    username = f"dashboard-mariadb-{uuid.uuid4().hex}"
    with mariadb_app.app_context():
        account = User(username=username, role="user")
        account.set_password("fictional-dashboard-password")
        db.session.add(account)
        db.session.flush()
        other_account = User(
            username=f"dashboard-mariadb-other-{uuid.uuid4().hex}", role="user"
        )
        other_account.set_password("fictional-other-dashboard-password")
        db.session.add(other_account)
        db.session.flush()
        db.session.add_all(
            [
                DailyNutrition(
                    user_id=account.id,
                    date=date(2026, 7, 1),
                    source="qa_fixture",
                    calories=Decimal("1500"),
                    protein_g=Decimal("80"),
                ),
                DailyEnergy(
                    user_id=account.id,
                    date=date(2026, 7, 1),
                    source="qa_fixture",
                    total_calories=Decimal("2100"),
                ),
                DailyNutrition(
                    user_id=other_account.id,
                    date=date(2026, 7, 1),
                    source="qa_other_owner",
                    calories=Decimal("9999"),
                    protein_g=Decimal("999"),
                ),
            ]
        )
        db.session.commit()
        user_id = account.id
        other_user_id = other_account.id
        try:
            result = DashboardSummaryService().build(
                user_id,
                _range({"from": "2026-07-01", "to": "2026-07-07"}),
                "kg",
            )
            assert Decimal(result["summary"]["energy"]["consumed_total"]) == Decimal(
                "1500"
            )
            assert result["summary"]["energy"]["balance_total"] == "-600.000"
            assert Decimal(result["summary"]["protein"]["total"]) == Decimal("80")
            explain = db.session.execute(
                text(
                    "EXPLAIN SELECT calories FROM daily_nutrition "
                    "WHERE user_id = :user_id AND date BETWEEN :start AND :end"
                ),
                {
                    "user_id": user_id,
                    "start": date(2026, 7, 1),
                    "end": date(2026, 7, 7),
                },
            ).mappings().all()
            assert explain
            assert "daily_nutrition" in str(explain[0].get("possible_keys") or "")
        finally:
            db.session.execute(
                db.delete(User).where(User.id.in_([user_id, other_user_id]))
            )
            db.session.commit()
