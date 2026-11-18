"""Real Flask and domain seed; temporary synthetic SQLite for visual QA only."""
from datetime import date
import json
import os
from pathlib import Path
import sys
import tempfile

from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import create_app
from app.extensions import db
from app.services.demo_seed import seed_demo_data

storage = Path(tempfile.mkdtemp(prefix="ht-demo-browser-qa-"))
app = create_app({"TESTING": True, "SECRET_KEY": "fictional-demo-browser-qa-key-long-enough",
    "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (storage / "qa.sqlite").as_posix(),
    "SQLALCHEMY_ENGINE_OPTIONS": {}, "DATA_ROOT": storage, "UPLOAD_ROOT": storage / "raw",
    "GENERATED_UPLOAD_ROOT": storage / "generated", "PORTABILITY_ROOT": storage / "portability",
    "SCHEMA_ROOT": ROOT / "schemas", "DEMO_SEED_ENABLED": True, "DEMO_SEED_ENVIRONMENT": "test",
    "NUTRITION_INTELLIGENCE_ENABLED": True, "APP_TIMEZONE": "America/Mexico_City"})
os.environ["DEMO_USER_PASSWORD"] = "fictional-demo-browser-password"
with app.app_context():
    db.create_all()
    seed_demo_data(as_of=date(2026, 11, 18), confirmed=True)
server = make_server("127.0.0.1", 0, app)
print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "scope": "synthetic temporary QA"}), flush=True)
server.serve_forever()
