"""Explicit isolated QA only. No .env, /data, NAS or persistent Docker volumes."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import create_app
from app.extensions import db
from app.models import User, ExternalExercise
from app.services.exercise_catalog import sync_catalog, external_catalog
from app.services.exercise_catalog_source import FreeExerciseDBSource
from app.services.gym_programs import resolve_draft, confirm_program, preview_token
from app.services.importers.routine_draft import DeterministicParser


def build_app():
    storage = Path(os.environ["CATALOG_QA_ROOT"]).resolve()
    import tempfile
    assert storage.is_relative_to(Path(tempfile.gettempdir()).resolve()) and storage.name.startswith("ht-catalog-qa-")
    uri = "mysql+pymysql://catalog_qa:fictional-qa-password@127.0.0.1:33379/exercise_catalog_qa?charset=utf8mb4"
    return create_app({"SECRET_KEY": "fictional-catalog-qa-secret-not-production", "SQLALCHEMY_DATABASE_URI": uri,
        "DATA_ROOT": storage, "EXERCISE_CATALOG_ROOT": storage / "exercise-catalog", "UPLOAD_ROOT": storage / "uploads/raw", "GENERATED_UPLOAD_ROOT": storage / "uploads/generated",
        "SCHEMA_ROOT": ROOT / "schemas", "AI_ENABLED": False, "WTF_CSRF_ENABLED": True})


app = build_app()


if __name__ == "__main__":
    with app.app_context():
        if sys.argv[1] == "sync":
            report = sync_catalog(ref="f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5")
            print(json.dumps(report, indent=2), flush=True)
            (Path(os.environ["CATALOG_QA_ROOT"]) / "sync-report.json").write_text(json.dumps(report, indent=2))
            # Replay the downloaded, validated snapshot offline for idempotence.
            class Replay(FreeExerciseDBSource):
                source_revision = report["commit_sha"]
                def fetch(self, staging, ref, metadata_only=False):
                    import shutil
                    original = Path(os.environ["CATALOG_QA_ROOT"]) / "exercise-catalog" / self.source_id / self.source_revision
                    shutil.copytree(original, staging / "snapshot")
                    return staging / "snapshot"
            repeated = sync_catalog(source=Replay())
            assert repeated["added_rows"] == 0 and db.session.query(ExternalExercise).count() == report["exercise_count"]
            print("Full MariaDB sync + offline repeat: passed", flush=True)
        elif sys.argv[1] == "serve":
            user = db.session.execute(db.select(User).where(User.username == "catalog-qa")).scalar_one_or_none()
            if user is None:
                user = User(username="catalog-qa", role="user")
                user.set_password("fictional-catalog-qa-password")
                db.session.add(user); db.session.commit()
                rows = [row for row in external_catalog() if row.media][:3]
                source = "Day,Exercise,Sets,Reps\n" + "\n".join(f"QA Day,{row.name},2,8" for row in rows)
                draft = DeterministicParser().parse(source.encode(), "qa.csv", "QA · Catálogo local")
                draft.days[0]["exercises"].append({"raw_name": "QA sin referencia", "create_new": True, "sets": [{"set_number": 1, "reps": 8}]})
                resolve_draft(draft, user.id)
                confirm_program(draft, user.id, preview_token(draft, user.id)); db.session.commit()
            # Fundamental offline gate: any outbound attempt in runtime fails.
            import socket
            def offline(*args, **kwargs):
                raise RuntimeError("Outbound network forbidden in catalog QA runtime")
            # SQLAlchemy's existing local DB pool stays usable; HTTP transport is blocked.
            import urllib.request
            urllib.request.OpenerDirector.open = offline
    if sys.argv[1] == "serve":
        app.run(host="127.0.0.1", port=8013, use_reloader=False)
