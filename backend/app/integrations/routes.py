from datetime import datetime, timezone
import hashlib
import secrets

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import csrf, db
from app.integrations import integrations_bp
from app.services.integrations.accounts import (
    ExternalIntegrationError,
    connect_account,
    disconnect_account,
    list_accounts,
    sanitized_account,
)
from app.services.integrations.base import IntegrationProviderError
from app.services.integrations.registry import provider_registry
from app.services.integrations.sync import sync_account
from app.services.integrations.webhooks import (
    WebhookPayloadError,
    enqueue_strava_event,
)


OAUTH_STATE_KEY = "integration_oauth_strava"
OAUTH_STATE_TTL_SECONDS = 600
WEBHOOK_MAX_BYTES = 16 * 1024


@integrations_bp.after_request
def private_integration_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _callback_uri() -> str:
    return f"{current_app.config['PUBLIC_BASE_URL']}{url_for('integrations.strava_callback')}"


def _flash_error(error: ExternalIntegrationError | IntegrationProviderError) -> None:
    db.session.rollback()
    flash(error.safe_message, "danger" if error.status >= 500 else "warning")


@integrations_bp.get("/integrations")
@login_required
def index():
    accounts = [sanitized_account(row) for row in list_accounts(current_user.id, "strava")]
    return render_template(
        "integrations/index.html",
        strava_enabled=bool(current_app.config.get("STRAVA_ENABLED")),
        accounts=accounts,
        default_initial_days=current_app.config["STRAVA_INITIAL_SYNC_DAYS"],
    )


@integrations_bp.route("/integrations/strava/connect", methods=["GET", "POST"])
@login_required
def strava_connect():
    try:
        provider = provider_registry.get("strava")
    except IntegrationProviderError as error:
        _flash_error(error)
        return redirect(url_for("integrations.index"))
    state = secrets.token_urlsafe(32)
    session[OAUTH_STATE_KEY] = {
        "digest": hashlib.sha256(state.encode("utf-8")).hexdigest(),
        "user_id": current_user.id,
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
    }
    session.modified = True
    return redirect(provider.build_authorization_url(state=state, redirect_uri=_callback_uri()))


@integrations_bp.get("/integrations/strava/callback")
@login_required
def strava_callback():
    stored = session.pop(OAUTH_STATE_KEY, None)
    state = request.args.get("state", "")
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    valid_state = (
        isinstance(stored, dict)
        and stored.get("user_id") == current_user.id
        and isinstance(stored.get("issued_at"), int)
        and 0 <= now_epoch - stored["issued_at"] <= OAUTH_STATE_TTL_SECONDS
        and isinstance(stored.get("digest"), str)
        and secrets.compare_digest(
            stored["digest"], hashlib.sha256(state.encode("utf-8")).hexdigest()
        )
    )
    if not valid_state:
        flash("La autorización de Strava no pudo validarse. Iníciala de nuevo.", "warning")
        return redirect(url_for("integrations.index"))
    if request.args.get("error") == "access_denied":
        flash("Cancelaste la autorización de Strava; no se guardó ninguna conexión.", "warning")
        return redirect(url_for("integrations.index"))
    code = request.args.get("code", "")
    if not code or len(code) > 2048:
        flash("Strava no devolvió un código de autorización válido.", "warning")
        return redirect(url_for("integrations.index"))
    callback_scopes = tuple(
        value for value in request.args.get("scope", "").replace(",", " ").split() if value
    )
    try:
        provider = provider_registry.get("strava")
        account = connect_account(
            current_user.id,
            provider_name="strava",
            code=code,
            redirect_uri=_callback_uri(),
            callback_scopes=callback_scopes,
            provider=provider,
        )
    except (ExternalIntegrationError, IntegrationProviderError) as error:
        _flash_error(error)
        return redirect(url_for("integrations.index"))
    try:
        summary = sync_account(
            current_user.id,
            account.public_id,
            mode="initial",
            initial_days=current_app.config["STRAVA_INITIAL_SYNC_DAYS"],
            provider=provider,
        )
    except ExternalIntegrationError as error:
        flash(
            f"Strava quedó conectado, pero el primer sync no terminó: {error.safe_message}",
            "warning",
        )
    else:
        flash(
            "Strava conectado. "
            f"Importadas: {summary['imported']}; actualizadas: {summary['updated']}; "
            f"sin cambios: {summary['skipped']}.",
            "success",
        )
    return redirect(url_for("integrations.index"))


@integrations_bp.post("/integrations/strava/sync")
@login_required
def strava_sync():
    account_id = request.form.get("account_id", "")
    mode = request.form.get("range", "incremental")
    if mode not in {"incremental", "30", "90", "full"}:
        flash("Selecciona un rango de sincronización válido.", "warning")
        return redirect(url_for("integrations.index"))
    if mode == "full" and request.form.get("confirm_full_history") != "yes":
        flash("Confirma explícitamente la sincronización del historial completo.", "warning")
        return redirect(url_for("integrations.index"))
    try:
        summary = sync_account(current_user.id, account_id, mode=mode)
    except ExternalIntegrationError as error:
        _flash_error(error)
    else:
        flash(
            f"Sync terminado: {summary['imported']} importadas, "
            f"{summary['updated']} actualizadas y {summary['skipped']} sin cambios.",
            "success",
        )
    return redirect(url_for("integrations.index"))


@integrations_bp.post("/integrations/strava/disconnect")
@login_required
def strava_disconnect():
    if request.form.get("confirm_disconnect") != "yes":
        flash("Confirma que deseas desconectar Strava.", "warning")
        return redirect(url_for("integrations.index"))
    try:
        _account, pending = disconnect_account(
            current_user.id, request.form.get("account_id", "")
        )
    except ExternalIntegrationError as error:
        _flash_error(error)
    else:
        if pending:
            flash(
                "Strava se desconectó localmente. La revocación remota quedó pendiente para un retry seguro.",
                "warning",
            )
        else:
            flash("Strava se desconectó. Las actividades históricas se conservaron.", "success")
    return redirect(url_for("integrations.index"))


@integrations_bp.get("/integrations/strava/webhook")
@csrf.exempt
def strava_webhook_verify():
    if not current_app.config.get("STRAVA_ENABLED"):
        abort(404)
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    expected = current_app.config["STRAVA_WEBHOOK_VERIFY_TOKEN"]
    if (
        mode != "subscribe"
        or not challenge
        or len(challenge) > 512
        or not secrets.compare_digest(token, expected)
    ):
        abort(403)
    return jsonify({"hub.challenge": challenge})


@integrations_bp.post("/integrations/strava/webhook")
@csrf.exempt
def strava_webhook_event():
    if not current_app.config.get("STRAVA_ENABLED"):
        abort(404)
    if request.content_length is not None and request.content_length > WEBHOOK_MAX_BYTES:
        return jsonify({"error": "invalid_event"}), 400
    content = request.get_data(cache=True)
    if len(content) > WEBHOOK_MAX_BYTES or not request.is_json:
        return jsonify({"error": "invalid_event"}), 400
    try:
        _row, duplicate = enqueue_strava_event(request.get_json(silent=True))
    except WebhookPayloadError:
        return jsonify({"error": "invalid_event"}), 400
    return jsonify({"accepted": True, "duplicate": duplicate}), 200
