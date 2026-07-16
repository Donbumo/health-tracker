from pathlib import Path
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, jsonify, render_template, request, session
from flask_login import current_user
from flask_wtf.csrf import CSRFError

from app.cli import register_commands
from app.config import Config
from app.extensions import csrf, db, login_manager, migrate
from app.models import User


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    engine_options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    database_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if database_uri.startswith(("mysql", "mariadb")):
        engine_options.setdefault("isolation_level", "READ COMMITTED")
    else:
        engine_options.pop("isolation_level", None)
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options

    secret_key = app.config.get("SECRET_KEY") or ""
    insecure_secret_values = {
        "replace-with-a-long-random-secret",
        "changeme",
        "change-me",
        "secret",
        "development",
    }
    if len(secret_key) < 32 or secret_key.casefold() in insecure_secret_values:
        raise RuntimeError("SECRET_KEY must be a non-placeholder value of at least 32 characters")

    api_signing_key = app.config.get("API_TOKEN_SIGNING_KEY") or ""
    if api_signing_key and (
        len(api_signing_key) < 32
        or api_signing_key == "replace-with-a-long-random-secret"
    ):
        raise RuntimeError(
            "API_TOKEN_SIGNING_KEY must contain at least 32 non-placeholder characters"
        )
    if not api_signing_key:
        if app.config.get("API_REQUIRE_SEPARATE_SIGNING_KEY"):
            raise RuntimeError(
                "API_TOKEN_SIGNING_KEY is required by API_REQUIRE_SEPARATE_SIGNING_KEY"
            )
        app.config["API_TOKEN_SIGNING_KEY"] = secret_key
        app.logger.warning(
            "API_TOKEN_SIGNING_KEY is not configured; using validated SECRET_KEY "
            "with the API-specific signing salt"
        )

    Path(app.config["UPLOAD_ROOT"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["GENERATED_UPLOAD_ROOT"]).mkdir(parents=True, exist_ok=True)

    schema_root = Path(app.config["SCHEMA_ROOT"])
    if not schema_root.is_dir():
        raise RuntimeError(f"SCHEMA_ROOT does not exist: {schema_root}")
    try:
        ZoneInfo(app.config["APP_TIMEZONE"])
    except ZoneInfoNotFoundError as error:
        raise RuntimeError("APP_TIMEZONE must be a valid IANA timezone") from error

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.auth import auth_bp
    from app.admin import admin_bp
    from app.activities import activities_bp
    from app.body import body_bp
    from app.main import main_bp
    from app.medical import medical_bp
    from app.progress import progress_bp
    from app.sessions import sessions_bp
    from app.training import training_bp
    from app.wellness import wellness_bp
    from app.foods import foods_bp
    from app.exports import exports_bp
    from app.recipes import recipes_bp
    from app.api_v1 import api_v1_bp
    from app.planned import planned_bp
    from app.workout_drafts import workout_drafts_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(body_bp)
    app.register_blueprint(medical_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(wellness_bp)
    app.register_blueprint(foods_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(planned_bp)
    app.register_blueprint(workout_drafts_bp)
    csrf.exempt(api_v1_bp)
    app.register_blueprint(api_v1_bp)
    register_commands(app)

    @app.after_request
    def secure_api_fallback_responses(response):
        if request.path.startswith("/api/v1"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.context_processor
    def inject_release_context():
        return {
            "alpha_release_label": "Alpha 0.8",
        }

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/v1"):
            return jsonify(
                error={"code": "not_found", "message": "Recurso no encontrado.", "details": {}},
                meta={"api_version": "1", "request_id": str(uuid.uuid4())},
            ), 404
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        if request.path.startswith("/api/v1"):
            return jsonify(
                error={"code": "method_not_allowed", "message": "Método no permitido.", "details": {}},
                meta={"api_version": "1", "request_id": str(uuid.uuid4())},
            ), 405
        return render_template("404.html"), 405

    @app.errorhandler(413)
    def request_too_large(_error):
        return render_template("413.html"), 413

    @app.errorhandler(CSRFError)
    def csrf_failed(error):
        request_id = str(uuid.uuid4())
        app.logger.warning(
            "csrf_rejected request_id=%s endpoint=%s authenticated=%s",
            request_id,
            request.endpoint or "unknown",
            bool(current_user.is_authenticated),
        )
        if request.path.startswith("/api/v1") or request.is_json:
            return jsonify(
                error={
                    "code": "csrf_failed",
                    "message": "El token de seguridad no es válido o venció.",
                    "details": {},
                },
                meta={"api_version": "1", "request_id": request_id},
            ), 403
        if (
            request.endpoint == "sessions.new_session"
            and current_user.is_authenticated
        ):
            from app.sessions.routes import render_csrf_recovery

            session.pop("csrf_token", None)
            g.pop("csrf_token", None)
            return render_csrf_recovery(request_id=request_id)
        return render_template(
            "csrf_recovery.html",
            request_id=request_id,
            reason=error.description,
        ), 400

    return app


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
