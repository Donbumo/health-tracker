"""Explicit gate on the disposable network-isolated demo_history_qa DB only."""
import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from flask_migrate import check
from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import DailyNutrition, TrainingSession, TrainingSet, User
from app.services.demo_seed import seed_demo_data, DEMO_EMAIL
from app.services.daily_balance import daily_balance


with TemporaryDirectory(prefix="ht-demo-qa-") as folder:
    root = Path(folder)
    app = create_app({
        "TESTING": True, "SECRET_KEY": "fictional-demo-mariadb-qa-secret-long-enough",
        "SQLALCHEMY_DATABASE_URI": "mysql+pymysql://qa:fictional-qa-only@127.0.0.1/demo_history_qa",
        "SQLALCHEMY_ENGINE_OPTIONS": {"isolation_level": os.environ.get("QA_ISOLATION", "READ COMMITTED")},
        "DATA_ROOT": root, "UPLOAD_ROOT": root / "raw", "GENERATED_UPLOAD_ROOT": root / "generated",
        "PORTABILITY_ROOT": root / "portability", "SCHEMA_ROOT": Path("/schemas"),
        "DEMO_SEED_ENABLED": True, "DEMO_SEED_ENVIRONMENT": "test", "NUTRITION_INTELLIGENCE_ENABLED": True,
    })
    os.environ["DEMO_USER_PASSWORD"] = "fictional-mariadb-demo-password"
    with app.app_context():
        assert db.session.scalar(text("SELECT DATABASE()")) == "demo_history_qa"
        assert db.session.scalar(text("SELECT CURRENT_USER()")).startswith("qa@")
        assert db.session.scalar(text("SELECT version_num FROM alembic_version")) == "20261018_0046"
        sentinel = db.session.scalar(db.select(User).where(User.username == "fictional-demo-sentinel"))
        if sentinel is None:
            sentinel = User(username="fictional-demo-sentinel", role="user")
            sentinel.set_password("fictional-sentinel-password")
            db.session.add(sentinel)
            db.session.commit()
        original = (sentinel.id, sentinel.username, sentinel.password_hash)
        user, created = seed_demo_data(as_of=date(2026, 11, 18), confirmed=True)
        _, replay = seed_demo_data(as_of=date(2026, 11, 18), confirmed=True)
        assert not any(replay.values())
        assert original == (sentinel.id, sentinel.username, sentinel.password_hash)
        assert not db.session.scalar(db.select(DailyNutrition.id).where(DailyNutrition.user_id == sentinel.id))
        assert db.session.scalar(db.select(db.func.count()).select_from(DailyNutrition).where(DailyNutrition.user_id == user.id)) == 49
        assert db.session.scalar(db.select(db.func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id)) == 21
        assert db.session.scalar(db.select(db.func.count()).select_from(TrainingSet).where(TrainingSet.user_id == user.id)) == 378
        for day in db.session.scalars(db.select(DailyNutrition).where(DailyNutrition.user_id == user.id)):
            balance = daily_balance(user.id, day.date)
            assert balance["complete"] and balance["balance"] == day.calories - balance["calories_expended"]
        client = app.test_client()
        app.config["WTF_CSRF_ENABLED"] = False
        assert client.post("/login", data={"username": DEMO_EMAIL, "password": os.environ["DEMO_USER_PASSWORD"]}).status_code == 302
        for path in ("/dashboard?from=2026-10-01&to=2026-11-18", "/energy?date=2026-11-18", "/nutrition/?date=2026-11-18", "/gym"):
            assert client.get(path, follow_redirects=True).status_code == 200, path
        check(directory="/app/migrations")
        print(json.dumps({"isolation": db.session.scalar(text("SELECT @@tx_isolation")), "created": created,
                          "replay_created": sum(replay.values()), "other_owner_unchanged": True,
                          "login_and_dashboards": "pass", "db_check": "pass"}))
