"""Isolated acceptance QA against the exact reviewed history implementation.

Loads four modules read-only from a local Git ref; never merges/cherry-picks them.
Requires PYTHONPATH=backend and a disposable empty database. Default is RAM SQLite.
All generated records are fictitious; public USDA foods are not personal data.
"""
import argparse
from collections import Counter
from datetime import date
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db


def history_modules(root, ref):
    # Fixed paths; the caller must supply a trusted, inspected local commit.
    for name in ("demo_fixtures", "gym_sessions", "importers.weigh_in", "demo_seed"):
        full = "app.services." + name
        path = "backend/" + full.replace(".", "/") + ".py"
        source = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=root)
        module = types.ModuleType(full)
        module.__file__ = f"git:{ref}:{path}"
        module.__package__ = full.rsplit(".", 1)[0]
        sys.modules[full] = module
        setattr(importlib.import_module(module.__package__), full.rsplit(".", 1)[1], module)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    return sys.modules["app.services.demo_seed"]


def fingerprints():
    """Hash, never print, all rows including passwords, timestamps and JSON."""
    result = {}
    for table in db.metadata.sorted_tables:
        if table.name == "user_goals":
            continue
        rows = [json.dumps(dict(row), sort_keys=True, default=str) for row in db.session.execute(table.select()).mappings()]
        result[table.name] = (len(rows), hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest())
    return result


def concurrency_checks(app, owner_id):
    """Only called inside the explicitly empty/disposable MariaDB QA database."""
    from app.models import UserGoal
    from app.services.demo_goals import seed_demo_goals
    results = []
    for isolation in ("READ COMMITTED", "REPEATABLE READ"):
        barrier = Barrier(2)
        def provision(_):
            with app.app_context():
                db.session.connection(execution_options={"isolation_level": isolation})
                barrier.wait(timeout=10)
                result = seed_demo_goals(confirmed=True)
                db.session.commit()
                return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(provision, range(2)))
        assert sum(len(r["created"]) for r in reports) == 7
        assert sum(len(r["reused"]) for r in reports) == 7
        assert not any(r["conflicts"] for r in reports)
        assert db.session.query(UserGoal).filter_by(user_id=owner_id).count() == 7
        # Reset this QA-only experiment before the acceptance fingerprint run.
        db.session.execute(db.delete(UserGoal).where(UserGoal.user_id == owner_id))
        db.session.commit()
        results.append({"isolation": isolation, "created": 7, "reused": 7})
    return results


def run(root, demo_ref):
    from app.models import DailyEnergy, DailyNutrition, NutritionItem, TrainingSession, TrainingSet, User, WeighIn
    from app.models.nutrition_intelligence import MealLog
    from app.services import food_catalog
    from app.services.dashboard import DashboardDateRange, DashboardSummaryService
    from app.services.demo_goals import seed_demo_goals
    from app.services.engagement import adherence_summary
    from app.services.mobile_health import health_today, health_progress
    from app.services.nutrition_portability import export_bundle, validate_bundle

    seed = history_modules(root, demo_ref)
    document = json.loads((root / "examples/catalog/nutrition-2-1/usda_sr_legacy.json").read_text(encoding="utf-8"))
    wanted = {v[0] for v in seed.FOODS.values()}
    document["foods"] = [f for f in document["foods"] if f["source_food_id"] in wanted]
    assert len(document["foods"]) == len(wanted) == 16
    food_catalog.stage(document)
    food_catalog.activate(document["source"], document["revision"], 1)
    db.session.commit()
    os.environ["DEMO_USER_PASSWORD"] = "Fictitious-acceptance-QA-password-only"
    owner, created = seed.seed_demo_data(as_of=date(2026, 11, 18), confirmed=True)
    db.session.commit()
    other = User(username="QA other untouched account", role="user")
    other.set_password("Fictitious-other-QA-only")
    db.session.add(other)
    db.session.commit()
    from flask import current_app
    races = concurrency_checks(current_app._get_current_object(), owner.id) if db.engine.dialect.name != "sqlite" else []
    baseline = fingerprints()
    report = seed_demo_goals(confirmed=True)
    db.session.commit()
    replay = seed_demo_goals(confirmed=True)
    db.session.commit()
    assert len(report["created"]) == len(replay["reused"]) == 7
    assert not report["conflicts"] and not replay["created"]
    counts = {model.__tablename__: db.session.query(model).filter_by(user_id=owner.id).count()
              for model in (DailyNutrition, DailyEnergy, NutritionItem, MealLog, TrainingSession, TrainingSet, WeighIn)}
    assert counts == {"daily_nutrition": 49, "daily_energy": 49, "nutrition_items": 196,
                      "meal_logs": 196, "training_sessions": 21, "training_sets": 378, "weigh_ins": 49}
    compositions = db.session.query(WeighIn).filter(WeighIn.user_id == owner.id, WeighIn.body_fat_percentage.is_not(None)).count()
    assert compositions == 21
    days = db.session.scalars(db.select(DailyNutrition).where(DailyNutrition.user_id == owner.id)).all()
    states = Counter((d.nutrition_summary_json["carbohydrate_total"]["state"],
                      d.nutrition_summary_json["net_carbs"]["state"]) for d in days)
    assert states == {("complete", "unknown"): 49}
    summaries = {}
    for start, end in [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-18"),
                       ("2026-11-12", "2026-11-18"), ("2026-09-01", "2026-09-30")]:
        date_range = DashboardDateRange.from_query({"from": start, "to": end}, "UTC")
        summary = DashboardSummaryService().build(owner.id, date_range, "kg")
        assert len(summary["goals"]) == (0 if start < "2026-10" else 7)
        if summary["goals"]:
            carbs = summary["summary"]["nutrition"]["averages"]["total_carbs"]
            assert carbs["days"] == carbs["goal_days"] == carbs["goal_data_days"] == date_range.days
            assert carbs["average"] is not None and carbs["percent_of_goal"] is not None
            nets = summary["summary"]["nutrition"]["averages"]["net_carbs"]
            assert nets["average"] is None and nets["days"] == 0 and nets["goal"] is None
            summaries[start] = {"total_carbs_average": carbs["average"], "days": carbs["days"],
                                "goals": [{k: g[k] for k in ("type", "actual", "target", "percent", "data_days", "applicable_days")} for g in summary["goals"]]}
    adherence = adherence_summary(owner, days=7, end=date(2026, 11, 18), timezone_name="UTC")
    carb_goal = next(i for i in adherence["items"] if i["goal"]["goal_type"] == "nutrition_carbohydrates")
    assert carb_goal["details"]["data_days"] == 7 and carb_goal["details"]["registered_percent_of_target"] is not None
    today = health_today(owner.id, date(2026, 11, 18), "UTC")
    assert today["nutrition"]["totals"]["carbohydrate_g"] is not None
    progress = health_progress(owner.id, date(2026, 10, 1), date(2026, 11, 18), "UTC")
    assert len(progress["points"]) == 49 and all(p["carbohydrate_g"] is not None for p in progress["points"])
    bundle = export_bundle(owner.id)
    validate_bundle(bundle)
    client = __import__("flask").current_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(owner.id)
        session["_fresh"] = True
    daily_id = next(day.id for day in days if day.date == date(2026, 11, 18))
    for url in ("/dashboard?from=2026-11-12&to=2026-11-18", "/nutrition/?date=2026-11-18",
                "/daily-nutrition", f"/daily-nutrition/{daily_id}", "/daily-balance?date=2026-11-18"):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        assert "Carbohidratos totales" in response.text
    assert fingerprints() == baseline, "A reader or goal seeding changed historical/other-user data"
    assert not DashboardSummaryService().build(other.id, date_range, "kg")["goals"]
    return {"qa_only": True, "engine": db.engine.dialect.name, "demo_ref": demo_ref,
            "counts": counts, "composition_days": compositions, "nutrient_states": {"complete_total_unknown_net": 49},
            "created_goals": report["created"], "reused_goals": replay["reused"],
            "history_unchanged": True, "concurrency": races, "summaries": summaries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-ref", required=True, help="Trusted inspected local history commit (QA only)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", type=int, help="Serve fictitious QA for browser validation on loopback")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    uri = os.getenv("DEMO_GOALS_QA_DATABASE_URI", "sqlite://")
    url = make_url(uri)
    if url.get_backend_name() not in {"sqlite", "mysql", "mariadb"} or url.host not in {None, "127.0.0.1", "localhost"}:
        raise SystemExit("QA requires a disposable loopback database")
    if url.get_backend_name() != "sqlite" and url.database != "demo_carbs_goals_qa":
        raise SystemExit("QA only permits the explicitly disposable database demo_carbs_goals_qa")
    with tempfile.TemporaryDirectory(prefix="health-tracker-demo-goals-qa-") as directory:
        data = Path(directory)
        app = create_app({"TESTING": True, "SECRET_KEY": "fictional-demo-goals-QA-key-long-enough", "SQLALCHEMY_DATABASE_URI": uri,
            "SQLALCHEMY_ENGINE_OPTIONS": {}, "DATA_ROOT": data, "UPLOAD_ROOT": data / "raw", "GENERATED_UPLOAD_ROOT": data / "generated",
            "PORTABILITY_ROOT": data / "portability", "SCHEMA_ROOT": root / "schemas", "APP_TIMEZONE": "UTC", "WTF_CSRF_ENABLED": False,
            "NUTRITION_INTELLIGENCE_ENABLED": True, "DEMO_SEED_ENABLED": True, "DEMO_SEED_ENVIRONMENT": "test",
            "DEMO_GOALS_ENABLED": True, "DEMO_GOALS_ENVIRONMENT": "test"})
        with app.app_context():
            if db.inspect(db.engine).get_table_names():
                raise SystemExit("QA requires an empty disposable database")
            if url.get_backend_name() == "sqlite":
                db.create_all()
            else:
                from flask_migrate import upgrade, check
                upgrade(directory=str(root / "backend/migrations"))
                check(directory=str(root / "backend/migrations"))
            result = run(root, args.demo_ref)
            encoded = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                args.output.write_text(encoded, encoding="utf-8")
            print(encoded, flush=True)
            if args.serve:
                from werkzeug.serving import make_server
                # Credentials remain QA-only; browser signs in using the ordinary login.
                server = make_server("127.0.0.1", args.serve, app, threaded=True)
                print(f"QA browser server on loopback port {server.server_port}", flush=True)
                server.serve_forever()


if __name__ == "__main__":
    main()
