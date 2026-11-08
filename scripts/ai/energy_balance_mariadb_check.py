"""Migration/check gate for the disposable, synthetic energy QA container only.

Run from backend with the repository virtualenv. Never reads an env file.
"""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from flask_migrate import upgrade, check
from sqlalchemy import text
from app import create_app
from app.extensions import db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="ht-energy-qa-") as temporary:
        storage = Path(temporary)
        application = create_app({
            "TESTING": True, "SECRET_KEY": "fictional-qa-signing-key-for-disposable-db",
            "SQLALCHEMY_DATABASE_URI": f"mysql+pymysql://qa:fictional-qa-only@127.0.0.1:{args.port}/energy_balance_qa",
            "SQLALCHEMY_ENGINE_OPTIONS": {}, "DATA_ROOT": storage,
            "UPLOAD_ROOT": storage / "raw", "GENERATED_UPLOAD_ROOT": storage / "generated",
            "PORTABILITY_ROOT": storage / "portability", "SCHEMA_ROOT": ROOT / "schemas",
        })
        with application.app_context():
            assert db.session.scalar(text("SELECT DATABASE()")) == "energy_balance_qa"
            assert db.session.scalar(text("SELECT CURRENT_USER()")).startswith("qa@")
            version = db.session.scalar(text("SELECT VERSION()"))
            db.session.rollback()
            upgrade(directory=str(ROOT / "backend/migrations"))
            check(directory=str(ROOT / "backend/migrations"))
            head = db.session.scalar(text("SELECT version_num FROM alembic_version"))
            print(json.dumps({"scope": "disposable MariaDB; synthetic fixtures only", "version": version,
                              "head": head, "db_check": "pass", "new_migrations": 0}))


if __name__ == "__main__":
    main()
