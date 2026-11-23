"""Loopback-only application for factual Exchange browser QA."""

from pathlib import Path
import tempfile

from app import create_app
from app.extensions import db
from app.models import User
from app.services import nutrition_import as imports, nutrition_import_review as compact
from flask_login import current_user, login_required

root = Path(tempfile.mkdtemp(prefix="htnx-browser-fictional-"))
repository = Path(__file__).resolve().parents[2]
app = create_app({
    "SECRET_KEY": "fictional-exchange-browser-signing-key-only",
    "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (root / "qa.sqlite").as_posix(),
    "SQLALCHEMY_ENGINE_OPTIONS": {},
    "DATA_ROOT": root,
    "UPLOAD_ROOT": root / "uploads/raw",
    "GENERATED_UPLOAD_ROOT": root / "uploads/generated",
    "PORTABILITY_ROOT": root / "portability",
    "SCHEMA_ROOT": repository / "schemas",
    "NUTRITION_INTELLIGENCE_ENABLED": True,
    "NUTRITION_EXCHANGE_ENABLED": True,
    "NUTRITION_QA_LABEL": True,
    "AI_ENABLED": False,
    "NUTRITION_EXTERNAL_LOOKUP_ENABLED": False,
})
with app.app_context():
    db.create_all()
    for label in ("desktop", "mobile"):
        person = User(username="htnx-fixture-" + label, role="user")
        person.set_password("only-fictional-exchange-password")
        db.session.add(person)
    db.session.commit()


@app.get("/qa/state/<key>")
@login_required
def state(key):
    row = imports.owned(current_user.id, key)
    view = compact.overview(row)
    return {
        "counts": view["counts"],
        "groups": len(view["groups"]),
        "energy": view["batch_summary"]["energy"]["value"],
        "nutrients": len(view["batch_summary"]),
    }


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8067, use_reloader=False, load_dotenv=False)
