from pathlib import Path

from flask import Flask, render_template

from app.cli import register_commands
from app.config import Config
from app.extensions import csrf, db, login_manager, migrate
from app.models import User


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    secret_key = app.config.get("SECRET_KEY") or ""
    if len(secret_key) < 32 or secret_key == "replace-with-a-long-random-secret":
        raise RuntimeError("SECRET_KEY must be a non-placeholder value of at least 32 characters")

    Path(app.config["UPLOAD_ROOT"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.auth import auth_bp
    from app.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    register_commands(app)

    @app.errorhandler(413)
    def request_too_large(_error):
        return render_template("413.html"), 413

    return app


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
