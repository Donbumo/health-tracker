import json
import hashlib
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.main import main_bp
from app.main.forms import (
    StandardImportConfirmForm,
    StandardImportPreviewForm,
    UploadForm,
    UserDataPreviewForm,
    WeighInForm,
)
from app.models import UploadedFile
from app.services.files import UploadError, store_uploaded_file
from app.services.files import mark_import_status
from app.services.daily_dashboard import daily_health_dashboard
from app.services.exporters.user_data import UserDataJsonExporter
from app.services.import_audit import ImportAuditService
from app.services.importers.weigh_in import WeighInImportError, import_weigh_in_file
from app.services.importers.user_data_preview import preview_user_data_import
from app.services.importers.standard_import_executor import (
    StandardImportError,
    StandardImportTokenError,
    StandardImportExecutor,
)
from app.services.importers.import_prompt_catalog import ImportPromptCatalog
from app.services.manual_json import (
    ManualJsonGenerationError,
    build_weigh_in_document,
    generate_standard_json,
)
from app.services.validation import JsonSchemaValidationError


@main_bp.get("/healthz")
def healthcheck():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Healthcheck database query failed")
        return jsonify(status="error", app="health-tracker"), 503
    return jsonify(status="ok", app="health-tracker")


@main_bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.get("/account/export.json")
@login_required
def export_account_data():
    artifact = UserDataJsonExporter().export(
        current_user._get_current_object(),
        current_user.id,
    )
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=f"health_tracker_user_{current_user.id}_export.json",
    )


@main_bp.route("/account/import-preview", methods=["GET", "POST"])
@login_required
def preview_account_import():
    form = UserDataPreviewForm()
    preview = None
    parse_error = None
    if form.validate_on_submit():
        maximum_bytes = 10 * 1024 * 1024
        raw = form.file.data.stream.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            parse_error = "El archivo supera el límite de 10 MB para el preview."
        else:
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except UnicodeDecodeError:
                parse_error = "El archivo debe usar codificación UTF-8."
            except json.JSONDecodeError as error:
                parse_error = (
                    "El archivo no contiene JSON válido "
                    f"(línea {error.lineno}, columna {error.colno})."
                )
            else:
                preview = preview_user_data_import(payload, current_user.id)
    return render_template(
        "account/import_preview.html",
        form=form,
        preview=preview,
        parse_error=parse_error,
    )


@main_bp.route("/imports/standard", methods=["GET", "POST"])
@login_required
def standard_import():
    preview_form = StandardImportPreviewForm()
    confirm_form = StandardImportConfirmForm()
    preview_result = None
    parse_error = None
    commit_result = None
    executor = StandardImportExecutor()
    prompt_catalog = ImportPromptCatalog()
    prompt_targets = prompt_catalog.as_dict()

    if request.method == "GET":
        requested_prompt_target = request.args.get("target")
        if requested_prompt_target in prompt_targets:
            preview_form.target_type.data = requested_prompt_target

    if request.method == "POST" and "payload_json" in request.form:
        if confirm_form.validate_on_submit():
            try:
                payload = json.loads(confirm_form.payload_json.data)
                target_type = confirm_form.target_type.data
                preview_result = executor.preview_payload(
                    payload,
                    user_id=current_user.id,
                    target_type=target_type,
                )
                executor.verify_confirmation_token(
                    confirm_form.confirmation_token.data,
                    user_id=current_user.id,
                    target_type=preview_result["target_type"],
                    payload=payload,
                    plan=preview_result["plan"],
                )
                token_digest = _standard_import_token_digest(
                    confirm_form.confirmation_token.data
                )
                used_tokens = session.setdefault("used_standard_import_tokens", [])
                if token_digest in used_tokens:
                    raise StandardImportTokenError(
                        "El token de confirmación ya fue usado."
                    )
                commit_result = executor.commit_documents(
                    preview_result["documents"],
                    user_id=current_user.id,
                    target_type=preview_result["target_type"],
                    confirmed=True,
                    audit_payload=payload,
                    audit_metadata={
                        "route": "/imports/standard",
                        "mode": "web_confirm",
                        "requested_type": target_type,
                        "detected_type": preview_result["target_type"],
                        "document_count": len(preview_result["documents"]),
                        "contract_version": "confirmed-standard-import-v1",
                    },
                )
                if commit_result["committed"]:
                    used_tokens.append(token_digest)
                    session["used_standard_import_tokens"] = used_tokens[-20:]
                    session.modified = True
            except (json.JSONDecodeError, StandardImportTokenError) as error:
                parse_error = f"No fue posible confirmar la importación: {error}"
                if preview_result is not None and preview_result["plan"]["total"] > 0:
                    _prepare_standard_import_confirmation(
                        confirm_form,
                        executor,
                        payload,
                        preview_result,
                    )
            except (StandardImportError, ValueError) as error:
                parse_error = f"No fue posible confirmar la importación: {error}"
            else:
                if commit_result["committed"]:
                    flash("Importación confirmada guardada correctamente.", "success")
                else:
                    flash(
                        "La importación no se guardó; revisa errores/conflictos.",
                        "warning",
                    )
        else:
            parse_error = "La confirmación no es válida."

    elif preview_form.validate_on_submit():
        maximum_bytes = 10 * 1024 * 1024
        raw = preview_form.file.data.stream.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            parse_error = "El archivo supera el límite de 10 MB para importación."
        else:
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
                target_type = preview_form.target_type.data or None
                preview_result = executor.preview_payload(
                    payload,
                    user_id=current_user.id,
                    requested_type=target_type,
                    target_type=target_type,
                )
                _prepare_standard_import_confirmation(
                    confirm_form,
                    executor,
                    payload,
                    preview_result,
                )
            except UnicodeDecodeError:
                parse_error = "El archivo debe usar codificación UTF-8."
            except json.JSONDecodeError as error:
                parse_error = (
                    "El archivo no contiene JSON válido "
                    f"(línea {error.lineno}, columna {error.colno})."
                )
            except (StandardImportError, ValueError) as error:
                parse_error = f"No fue posible preparar la importación: {error}"

    return render_template(
        "imports/standard.html",
        preview_form=preview_form,
        confirm_form=confirm_form,
        preview_result=preview_result,
        commit_result=commit_result,
        parse_error=parse_error,
        prompt_targets=prompt_targets,
    )


@main_bp.get("/imports/standard/prompts/<target_type>")
@login_required
def standard_import_prompt(target_type: str):
    try:
        prompt = ImportPromptCatalog().get(target_type)
    except KeyError:
        abort(404)
    return jsonify(prompt)


@main_bp.get("/imports/history")
@login_required
def import_history():
    page = _positive_int(request.args.get("page"), default=1)
    per_page = 20
    runs = ImportAuditService().list_runs(
        user_id=current_user.id,
        page=page,
        per_page=per_page,
    )
    return render_template(
        "imports/history.html",
        runs=runs,
        page=page,
        has_previous=page > 1,
        has_next=len(runs) == per_page,
    )


@main_bp.get("/imports/history/<int:run_id>")
@login_required
def import_history_detail(run_id: int):
    run = ImportAuditService().get_run(user_id=current_user.id, run_id=run_id)
    if run is None:
        abort(404)
    return render_template("imports/history_detail.html", run=run)


def _prepare_standard_import_confirmation(
    form: StandardImportConfirmForm,
    executor: StandardImportExecutor,
    payload: dict,
    preview_result: dict,
) -> None:
    form.payload_json.data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    form.target_type.data = preview_result["target_type"]
    form.confirmation_token.data = executor.build_confirmation_token(
        user_id=current_user.id,
        target_type=preview_result["target_type"],
        payload=payload,
        plan=preview_result["plan"],
    )


def _standard_import_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _positive_int(value: str | None, *, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _current_user_files():
    return db.session.execute(
        db.select(UploadedFile)
        .where(UploadedFile.user_id == current_user.id)
        .order_by(UploadedFile.created_at.desc())
    ).scalars()


@main_bp.get("/")
@login_required
def index():
    return _render_dashboard()


@main_bp.get("/dashboard")
@login_required
def dashboard():
    return _render_dashboard()


def _render_dashboard():
    app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
    target_date = datetime.now(app_timezone).date()
    requested_date = request.args.get("date", "").strip()
    if requested_date:
        try:
            target_date = datetime.strptime(requested_date, "%Y-%m-%d").date()
        except ValueError:
            flash("La fecha del dashboard no es válida; se muestra hoy.", "warning")
    return render_template(
        "index.html",
        summary=daily_health_dashboard(
            current_user.id,
            target_date,
            current_app.config["APP_TIMEZONE"],
        ),
    )


@main_bp.route("/uploads", methods=["GET", "POST"])
@login_required
def uploads():
    form = UploadForm()
    if form.validate_on_submit():
        try:
            record, duplicate = store_uploaded_file(form.file.data, current_user.id)
        except UploadError as error:
            flash(str(error), "danger")
        else:
            if duplicate:
                flash(
                    f"'{record.original_filename}' ya estaba registrado para tu usuario.",
                    "warning",
                )
            else:
                flash("Archivo guardado correctamente.", "success")
            return redirect(url_for("main.uploads"))

    return render_template("uploads/upload.html", form=form, files=_current_user_files())


@main_bp.route("/manual/weigh-in", methods=["GET", "POST"])
@login_required
def manual_weigh_in():
    app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
    form = WeighInForm()
    if not form.is_submitted():
        form.recorded_at.data = datetime.now(app_timezone).replace(
            tzinfo=None,
            second=0,
            microsecond=0,
        )

    if form.validate_on_submit():
        recorded_at = form.recorded_at.data.replace(tzinfo=app_timezone)
        document = build_weigh_in_document(
            user_id=current_user.id,
            recorded_at=recorded_at,
            weight_kg=form.weight_kg.data,
            body_fat_percent=form.body_fat_percent.data,
            muscle_mass_kg=form.muscle_mass_kg.data,
            water_percent=form.water_percent.data,
            visceral_fat=form.visceral_fat.data,
            bmr_kcal=form.bmr_kcal.data,
            bmi=form.bmi.data,
            notes=form.notes.data,
        )
        original_filename = f"weigh_in_{recorded_at.strftime('%Y%m%dT%H%M%S%z')}.json"

        source_file = None
        try:
            source_file, file_duplicate = generate_standard_json(
                document=document,
                schema_name="weigh_in",
                user_id=current_user.id,
                original_filename=original_filename,
            )
            weigh_in, record_duplicate = import_weigh_in_file(
                source_file,
                current_user.id,
            )
        except (
            JsonSchemaValidationError,
            ManualJsonGenerationError,
            WeighInImportError,
        ) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="weigh_in",
                    error_message=str(error),
                )
            flash(f"No fue posible generar el pesaje: {error}", "danger")
        else:
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="weigh_in",
            )
            if duplicate:
                flash("Este pesaje ya estaba registrado para tu usuario.", "warning")
            else:
                flash(
                    f"Pesaje guardado como '{source_file.original_filename}'.",
                    "success",
                )
            return redirect(url_for("body.weigh_in_detail", record_id=weigh_in.id))

    return render_template(
        "manual/weigh_in.html",
        form=form,
        timezone_name=current_app.config["APP_TIMEZONE"],
    )
