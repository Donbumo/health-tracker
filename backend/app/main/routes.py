import json
import hashlib
import os
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
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
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.main import main_bp
from app.main.forms import (
    AccountPreferencesForm,
    AccountBackupCreateForm,
    AccountBackupRestoreConfirmForm,
    AccountBackupRestorePreviewForm,
    AccountRestoreConfirmForm,
    AccountRestorePreviewForm,
    ImportHubConfirmForm,
    ImportHubPreviewForm,
    OnboardingDismissForm,
    RealFileImportConfirmForm,
    RealFileImportPreviewForm,
    StandardImportConfirmForm,
    StandardImportPreviewForm,
    UploadForm,
    UserDataPreviewForm,
    WeighInForm,
)
from app.models import ApiDevice, ExportRecord, ImportRun, UploadedFile
from app.api_v1.auth import revoke_session
from app.services.account_restore import (
    AccountRestoreError,
    AccountRestoreService,
    AccountRestoreTokenError,
    MAX_EXPORT_BYTES,
)
from app.services.backups import (
    AccountBackupService,
    BackupError,
    BackupRestoreCoordinator,
    BackupSecurityError,
    BackupTokenError,
    resolve_uploaded_download,
)
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
from app.services.importers.registry import ImportAdapterRegistry
from app.services.real_file_imports import (
    RealFileImportError,
    RealFileImportService,
    RealFileImportTokenError,
)
from app.services.importers.import_prompt_catalog import ImportPromptCatalog
from app.services.onboarding import getting_started_status
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


@main_bp.get("/getting-started")
@login_required
def getting_started():
    return render_template(
        "getting_started.html",
        onboarding=getting_started_status(current_user.id),
        dismiss_form=OnboardingDismissForm(),
    )


@main_bp.post("/getting-started/dismiss")
@login_required
def dismiss_getting_started():
    form = OnboardingDismissForm()
    if not form.validate_on_submit():
        abort(400)
    onboarding = getting_started_status(current_user.id)
    if not onboarding["required_complete"]:
        flash("Completa los pasos principales antes de ocultar esta guía.", "warning")
        return redirect(url_for("main.getting_started"))
    current_user.onboarding_dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("La guía seguirá disponible desde Ayuda.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/account/preferences", methods=["GET", "POST"])
@login_required
def account_preferences():
    form = AccountPreferencesForm(obj=current_user)
    if not form.is_submitted():
        form.timezone.data = current_user.timezone or current_app.config["APP_TIMEZONE"]
    if form.validate_on_submit():
        current_user.display_name = (form.display_name.data or "").strip() or None
        current_user.timezone = form.timezone.data.strip()
        current_user.preferred_load_unit = form.preferred_load_unit.data
        db.session.commit()
        flash("Preferencias guardadas.", "success")
        return redirect(url_for("main.account_preferences"))
    return render_template("account/preferences.html", form=form)


@main_bp.get("/help")
@login_required
def help_center():
    return render_template("help.html")


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


@main_bp.get("/account/data")
@login_required
def account_data():
    latest_runs = ImportAuditService().list_runs(
        user_id=current_user.id,
        page=1,
        per_page=1,
    )
    latest_run = latest_runs[0] if latest_runs else None
    backups = AccountBackupService().list_records(user_id=current_user.id)[:3]
    return render_template(
        "account/data.html",
        latest_run=latest_run,
        backups=backups,
    )


@main_bp.get("/account/devices")
@login_required
def account_devices():
    devices = db.session.execute(
        db.select(ApiDevice)
        .where(ApiDevice.user_id == current_user.id)
        .options(
            selectinload(ApiDevice.sessions),
            selectinload(ApiDevice.companion_profile),
            selectinload(ApiDevice.companion_deliveries),
        )
        .order_by(ApiDevice.last_seen_at.desc(), ApiDevice.created_at.desc())
    ).scalars().all()
    return render_template("account/devices.html", devices=devices)


@main_bp.post("/account/devices/<string:device_id>/revoke")
@login_required
def revoke_account_device(device_id: str):
    device = db.session.execute(
        db.select(ApiDevice).where(
            ApiDevice.user_id == current_user.id,
            ApiDevice.public_device_id == device_id,
        )
    ).scalar_one_or_none()
    if device is None:
        abort(404)
    now = datetime.now(timezone.utc)
    device.revoked_at = device.revoked_at or now
    for api_session in device.sessions:
        revoke_session(api_session, "device_revoked_web")
    db.session.commit()
    flash("Dispositivo revocado. Sus sesiones API ya no están activas.", "success")
    return redirect(url_for("main.account_devices"))


@main_bp.get("/account/system")
@login_required
def account_system():
    try:
        db.session.execute(text("SELECT 1"))
        counts = {
            "imports": db.session.execute(
                db.select(func.count(ImportRun.id)).where(
                    ImportRun.user_id == current_user.id
                )
            ).scalar_one(),
            "exports": db.session.execute(
                db.select(func.count(ExportRecord.id)).where(
                    ExportRecord.user_id == current_user.id,
                    ExportRecord.domain != "account_backup",
                )
            ).scalar_one(),
            "backups": db.session.execute(
                db.select(func.count(ExportRecord.id)).where(
                    ExportRecord.user_id == current_user.id,
                    ExportRecord.domain == "account_backup",
                )
            ).scalar_one(),
            "active_devices": db.session.execute(
                db.select(func.count(ApiDevice.id)).where(
                    ApiDevice.user_id == current_user.id,
                    ApiDevice.revoked_at.is_(None),
                )
            ).scalar_one(),
        }
        latest_backup = db.session.execute(
            db.select(ExportRecord)
            .where(
                ExportRecord.user_id == current_user.id,
                ExportRecord.domain == "account_backup",
            )
            .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
        ).scalars().first()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Account system status database check failed")
        database_status = "error"
        counts = None
        latest_backup = None
    else:
        database_status = "ok"
    migration_head = None
    if database_status == "ok":
        try:
            migration_head = db.session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        except SQLAlchemyError:
            db.session.rollback()
    storage_status = {
        "raw": _storage_available(current_app.config["UPLOAD_ROOT"]),
        "generated": _storage_available(current_app.config["GENERATED_UPLOAD_ROOT"]),
    }
    return render_template(
        "account/system.html",
        database_status=database_status,
        migration_head=migration_head or "unknown",
        app_version=current_app.config.get("APP_VERSION", "unknown"),
        server_time=datetime.now(timezone.utc),
        storage_status=storage_status,
        counts=counts,
        latest_backup=latest_backup,
        reconciliation_status="No persistido; disponible como dry-run por CLI.",
        api_signing_key_separate=current_app.config.get(
            "API_TOKEN_SIGNING_KEY_SEPARATE", False
        ),
        rate_limiter_scope="Por proceso",
    )


def _storage_available(path_value) -> bool:
    path = Path(path_value)
    return path.is_dir() and os.access(path, os.R_OK | os.W_OK)


@main_bp.get("/account/backups")
@login_required
def account_backups():
    records = AccountBackupService().list_records(user_id=current_user.id)
    return render_template("account/backups.html", records=records)


@main_bp.route("/account/backups/new", methods=["GET", "POST"])
@login_required
def new_account_backup():
    form = AccountBackupCreateForm()
    service = AccountBackupService()
    preview = service.preview(
        current_user._get_current_object(),
        user_id=current_user.id,
    )
    if form.validate_on_submit():
        try:
            record = service.create(
                current_user._get_current_object(),
                user_id=current_user.id,
            )
        except BackupError as error:
            flash(str(error), "danger")
        else:
            flash("Backup ZIP generado y verificado.", "success")
            return redirect(url_for("main.account_backup_detail", backup_id=record.id))
    return render_template("account/backup_new.html", form=form, preview=preview)


@main_bp.get("/account/backups/<int:backup_id>")
@login_required
def account_backup_detail(backup_id: int):
    record = AccountBackupService().get_record(
        user_id=current_user.id,
        backup_id=backup_id,
    )
    if record is None:
        abort(404)
    return render_template("account/backup_detail.html", record=record)


@main_bp.get("/account/backups/<int:backup_id>/download")
@login_required
def download_account_backup(backup_id: int):
    service = AccountBackupService()
    record = service.get_record(user_id=current_user.id, backup_id=backup_id)
    if record is None:
        abort(404)
    try:
        path = service.resolve_download(record, user_id=current_user.id)
    except BackupError:
        abort(404)
    response = send_file(
        path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=record.filename,
        conditional=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@main_bp.get("/account/uploads/<int:upload_id>/download")
@login_required
def download_account_upload(upload_id: int):
    record = db.session.execute(
        db.select(UploadedFile).where(
            UploadedFile.id == upload_id,
            UploadedFile.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    try:
        path = resolve_uploaded_download(record, user_id=current_user.id)
    except BackupError:
        abort(404)
    response = send_file(
        path,
        mimetype=record.mime_type or "application/octet-stream",
        as_attachment=True,
        download_name=record.original_filename,
        conditional=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@main_bp.route("/account/backups/restore", methods=["GET", "POST"])
@login_required
def restore_account_backup():
    form = AccountBackupRestorePreviewForm()
    confirm_form = AccountBackupRestoreConfirmForm()
    preview = None
    parse_error = None
    coordinator = BackupRestoreCoordinator()
    if form.validate_on_submit():
        staging_id = None
        try:
            staging_id = coordinator.stage_upload(form.file.data, user_id=current_user.id)
            preview = coordinator.preview(staging_id=staging_id, user_id=current_user.id)
            confirm_form.staging_id.data = staging_id
            confirm_form.confirmation_token.data = preview["confirmation_token"]
        except (BackupError, ValueError) as error:
            if staging_id:
                coordinator.cleanup_staging(user_id=current_user.id, staging_id=staging_id)
            parse_error = f"No fue posible preparar el backup: {error}"
    return render_template(
        "account/backup_restore.html",
        form=form,
        confirm_form=confirm_form,
        preview=preview,
        commit_result=None,
        parse_error=parse_error,
    )


@main_bp.post("/account/backups/restore/confirm")
@login_required
def confirm_account_backup_restore():
    form = AccountBackupRestoreConfirmForm()
    preview_form = AccountBackupRestorePreviewForm()
    commit_result = None
    parse_error = None
    if form.validate_on_submit():
        token_digest = _account_restore_token_digest(form.confirmation_token.data)
        used_tokens = session.setdefault("used_backup_restore_tokens", [])
        try:
            if token_digest in used_tokens:
                raise BackupTokenError("El token de restore completo ya fue usado.")
            commit_result = BackupRestoreCoordinator().confirm(
                staging_id=form.staging_id.data,
                user_id=current_user.id,
                confirmation_token=form.confirmation_token.data,
            )
            used_tokens.append(token_digest)
            session["used_backup_restore_tokens"] = used_tokens[-20:]
            session.modified = True
        except (BackupError, BackupSecurityError, BackupTokenError, ValueError) as error:
            parse_error = f"No fue posible confirmar el restore completo: {error}"
    else:
        parse_error = "La confirmación no es válida."
    return render_template(
        "account/backup_restore.html",
        form=preview_form,
        confirm_form=form,
        preview=None,
        commit_result=commit_result,
        parse_error=parse_error,
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


@main_bp.route("/account/restore", methods=["GET", "POST"])
@login_required
def restore_account_data():
    form = AccountRestorePreviewForm()
    confirm_form = AccountRestoreConfirmForm()
    preview = None
    parse_error = None
    service = AccountRestoreService()
    if form.validate_on_submit():
        try:
            payload = _read_json_upload(form.file.data, limit_bytes=MAX_EXPORT_BYTES)
            preview = service.preview(payload, user_id=current_user.id)
            confirm_form.confirmation_token.data = preview["confirmation_token"]
        except (AccountRestoreError, ValueError) as error:
            parse_error = f"No fue posible preparar el restore: {error}"
    return render_template(
        "account/restore.html",
        form=form,
        confirm_form=confirm_form,
        preview=preview,
        commit_result=None,
        parse_error=parse_error,
    )


@main_bp.post("/account/restore/confirm")
@login_required
def confirm_account_restore():
    form = AccountRestoreConfirmForm()
    preview_form = AccountRestorePreviewForm()
    preview = None
    commit_result = None
    parse_error = None
    service = AccountRestoreService()
    if form.validate_on_submit():
        try:
            payload = _read_json_upload(form.file.data, limit_bytes=MAX_EXPORT_BYTES)
            preview = service.preview(payload, user_id=current_user.id)
            token_digest = _account_restore_token_digest(
                form.confirmation_token.data
            )
            used_tokens = session.setdefault("used_account_restore_tokens", [])
            if token_digest in used_tokens:
                raise AccountRestoreTokenError(
                    "El token de confirmación de restore ya fue usado."
                )
            commit_result = service.commit(
                payload,
                user_id=current_user.id,
                confirmation_token=form.confirmation_token.data,
            )
            used_tokens.append(token_digest)
            session["used_account_restore_tokens"] = used_tokens[-20:]
            session.modified = True
        except (json.JSONDecodeError, AccountRestoreTokenError, AccountRestoreError, ValueError) as error:
            parse_error = f"No fue posible confirmar el restore: {error}"
    else:
        parse_error = "La confirmación no es válida."
    return render_template(
        "account/restore.html",
        form=preview_form,
        confirm_form=form,
        preview=preview,
        commit_result=commit_result,
        parse_error=parse_error,
    )


@main_bp.route("/imports", methods=["GET", "POST"])
@login_required
def import_hub():
    preview_form = ImportHubPreviewForm()
    if request.method == "GET":
        requested_type = (request.args.get("requested_type") or "").strip()
        allowed_types = {value for value, _label in preview_form.requested_type.choices}
        if requested_type in allowed_types:
            preview_form.requested_type.data = requested_type
    confirm_form = ImportHubConfirmForm()
    preview_result = None
    commit_result = None
    parse_error = None
    source_file = None
    mode = None
    standard_executor = StandardImportExecutor()
    real_service = RealFileImportService()
    adapter_specs = ImportAdapterRegistry().specs

    if request.method == "POST" and "mode" in request.form:
        if not confirm_form.validate_on_submit():
            parse_error = "La confirmación no es válida; vuelve a revisar el archivo."
        elif confirm_form.mode.data == "standard":
            try:
                payload = json.loads(confirm_form.payload_json.data or "")
                preview_result = standard_executor.preview_payload(
                    payload,
                    user_id=current_user.id,
                    target_type=confirm_form.target_type.data,
                )
                standard_executor.verify_confirmation_token(
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
                    raise StandardImportTokenError("El token de confirmación ya fue usado.")
                commit_result = standard_executor.commit_documents(
                    preview_result["documents"],
                    user_id=current_user.id,
                    target_type=preview_result["target_type"],
                    confirmed=True,
                    audit_payload=payload,
                    audit_metadata={
                        "route": "/imports",
                        "mode": "web_confirm",
                        "requested_type": confirm_form.requested_type.data or None,
                        "detected_type": preview_result["target_type"],
                        "document_count": len(preview_result["documents"]),
                        "contract_version": "confirmed-standard-import-v1",
                    },
                )
                if commit_result["committed"]:
                    used_tokens.append(token_digest)
                    session["used_standard_import_tokens"] = used_tokens[-20:]
                    session.modified = True
                    flash("Datos importados correctamente.", "success")
                else:
                    flash("No se guardaron datos; revisa el plan y sus errores.", "warning")
                mode = "standard"
            except (json.JSONDecodeError, StandardImportError, StandardImportTokenError, ValueError) as error:
                parse_error = f"No fue posible confirmar la importación: {error}"
        elif confirm_form.mode.data == "real_file":
            try:
                source_file_id = int(confirm_form.source_file_id.data or 0)
            except (TypeError, ValueError):
                source_file_id = 0
            source_file = db.session.execute(
                db.select(UploadedFile).where(
                    UploadedFile.id == source_file_id,
                    UploadedFile.user_id == current_user.id,
                )
            ).scalar_one_or_none()
            if source_file is None:
                abort(404)
            try:
                preview_result = real_service.preview_uploaded_file(
                    source_file,
                    user_id=current_user.id,
                    requested_type=confirm_form.requested_type.data or None,
                )
                token_digest = _real_file_import_token_digest(
                    confirm_form.confirmation_token.data
                )
                used_tokens = session.setdefault("used_real_file_import_tokens", [])
                if token_digest in used_tokens:
                    raise RealFileImportTokenError("El token de confirmación ya fue usado.")
                result = real_service.confirm_uploaded_file(
                    source_file,
                    user_id=current_user.id,
                    requested_type=confirm_form.requested_type.data or None,
                    confirmation_token=confirm_form.confirmation_token.data,
                )
                commit_result = result["commit_result"]
                if commit_result["committed"]:
                    used_tokens.append(token_digest)
                    session["used_real_file_import_tokens"] = used_tokens[-20:]
                    session.modified = True
                    flash("Archivo importado correctamente.", "success")
                else:
                    flash("No se guardaron datos; revisa el plan y sus errores.", "warning")
                mode = "real_file"
            except (RealFileImportError, RealFileImportTokenError, StandardImportError, ValueError) as error:
                parse_error = f"No fue posible confirmar el archivo: {error}"
        else:
            parse_error = "El modo de importación no es compatible."

    elif preview_form.validate_on_submit():
        filename = preview_form.file.data.filename or ""
        suffix = Path(filename).suffix.casefold()
        requested_type = preview_form.requested_type.data or None
        if suffix == ".json":
            if requested_type in {"weigh_in_csv", "daily_energy_csv"}:
                parse_error = "El perfil CSV seleccionado no corresponde a un archivo JSON."
            else:
                try:
                    payload = _read_json_upload(
                        preview_form.file.data,
                        limit_bytes=10 * 1024 * 1024,
                    )
                    preview_result = standard_executor.preview_payload(
                        payload,
                        user_id=current_user.id,
                        requested_type=requested_type,
                        target_type=requested_type,
                    )
                    mode = "standard"
                    _prepare_import_hub_standard_confirmation(
                        confirm_form,
                        standard_executor,
                        payload,
                        requested_type,
                        preview_result,
                    )
                except (StandardImportError, ValueError) as error:
                    parse_error = f"No fue posible preparar el JSON: {error}"
        else:
            if requested_type and requested_type not in {"weigh_in_csv", "daily_energy_csv"}:
                parse_error = "La selección manual indicada solo es compatible con JSON."
            else:
                try:
                    source_file, duplicate = store_uploaded_file(
                        preview_form.file.data,
                        current_user.id,
                    )
                    if duplicate:
                        flash("Este archivo ya existía; se muestra un preview idempotente.", "warning")
                    preview_result = real_service.preview_uploaded_file(
                        source_file,
                        user_id=current_user.id,
                        requested_type=requested_type,
                    )
                    mode = "real_file"
                    _prepare_import_hub_real_confirmation(
                        confirm_form,
                        source_file,
                        requested_type or "",
                        preview_result,
                    )
                except (UploadError, RealFileImportError, StandardImportError, ValueError) as error:
                    parse_error = f"No fue posible preparar el archivo: {error}"

    return render_template(
        "imports/hub.html",
        preview_form=preview_form,
        confirm_form=confirm_form,
        preview_result=preview_result,
        commit_result=commit_result,
        parse_error=parse_error,
        source_file=source_file,
        mode=mode,
        adapter_specs=adapter_specs,
        recent_runs=ImportAuditService().list_runs(
            user_id=current_user.id,
            page=1,
            per_page=5,
        ),
    )


@main_bp.get("/service-worker.js")
def service_worker():
    response = send_from_directory(
        current_app.static_folder,
        "js/service_worker.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


def _prepare_import_hub_standard_confirmation(
    form: ImportHubConfirmForm,
    executor: StandardImportExecutor,
    payload: dict,
    requested_type: str | None,
    preview_result: dict,
) -> None:
    form.mode.data = "standard"
    form.payload_json.data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, allow_nan=False
    )
    form.requested_type.data = requested_type or ""
    form.target_type.data = preview_result["target_type"]
    form.confirmation_token.data = executor.build_confirmation_token(
        user_id=current_user.id,
        target_type=preview_result["target_type"],
        payload=payload,
        plan=preview_result["plan"],
    )


def _prepare_import_hub_real_confirmation(
    form: ImportHubConfirmForm,
    source_file: UploadedFile,
    requested_type: str,
    preview_result: dict,
) -> None:
    form.mode.data = "real_file"
    form.source_file_id.data = str(source_file.id)
    form.requested_type.data = requested_type
    form.target_type.data = preview_result["target_type"]
    form.confirmation_token.data = preview_result["confirmation_token"]


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


@main_bp.route("/imports/files", methods=["GET", "POST"])
@login_required
def real_file_import():
    preview_form = RealFileImportPreviewForm()
    confirm_form = RealFileImportConfirmForm()
    preview_result = None
    commit_result = None
    parse_error = None
    source_file = None
    service = RealFileImportService()

    if request.method == "POST" and "source_file_id" in request.form:
        if confirm_form.validate_on_submit():
            try:
                source_file_id = int(confirm_form.source_file_id.data)
            except (TypeError, ValueError):
                source_file_id = 0
            source_file = db.session.execute(
                db.select(UploadedFile).where(
                    UploadedFile.id == source_file_id,
                    UploadedFile.user_id == current_user.id,
                )
            ).scalar_one_or_none()
            if source_file is None:
                abort(404)
            try:
                preview_result = service.preview_uploaded_file(
                    source_file,
                    user_id=current_user.id,
                    requested_type=confirm_form.requested_type.data or None,
                )
                token_digest = _real_file_import_token_digest(
                    confirm_form.confirmation_token.data
                )
                used_tokens = session.setdefault("used_real_file_import_tokens", [])
                if token_digest in used_tokens:
                    raise RealFileImportTokenError(
                        "El token de confirmación de archivo ya fue usado."
                    )
                result = service.confirm_uploaded_file(
                    source_file,
                    user_id=current_user.id,
                    requested_type=confirm_form.requested_type.data or None,
                    confirmation_token=confirm_form.confirmation_token.data,
                )
                commit_result = result["commit_result"]
                if commit_result["committed"]:
                    used_tokens.append(token_digest)
                    session["used_real_file_import_tokens"] = used_tokens[-20:]
                    session.modified = True
                    flash("Archivo importado correctamente.", "success")
                else:
                    flash("El archivo no se importó; revisa errores o conflictos.", "warning")
            except (RealFileImportError, RealFileImportTokenError, StandardImportError, ValueError) as error:
                parse_error = f"No fue posible confirmar el archivo: {error}"
        else:
            parse_error = "La confirmación del archivo no es válida."

    elif preview_form.validate_on_submit():
        try:
            source_file, duplicate = store_uploaded_file(
                preview_form.file.data,
                current_user.id,
            )
            if duplicate:
                flash("El archivo ya existía; se muestra preview idempotente.", "warning")
            preview_result = service.preview_uploaded_file(
                source_file,
                user_id=current_user.id,
                requested_type=preview_form.requested_type.data or None,
            )
            _prepare_real_file_import_confirmation(
                confirm_form,
                source_file,
                preview_form.requested_type.data or "",
                preview_result,
            )
        except (UploadError, RealFileImportError, StandardImportError, ValueError) as error:
            parse_error = f"No fue posible preparar el archivo: {error}"

    return render_template(
        "imports/files.html",
        preview_form=preview_form,
        confirm_form=confirm_form,
        preview_result=preview_result,
        commit_result=commit_result,
        parse_error=parse_error,
        source_file=source_file,
    )


def _prepare_real_file_import_confirmation(
    form: RealFileImportConfirmForm,
    source_file: UploadedFile,
    requested_type: str,
    preview_result: dict,
) -> None:
    form.source_file_id.data = str(source_file.id)
    form.requested_type.data = requested_type
    form.target_type.data = preview_result["target_type"]
    form.confirmation_token.data = preview_result["confirmation_token"]


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


def _account_restore_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _real_file_import_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_json_upload(storage, *, limit_bytes: int) -> dict:
    raw = storage.stream.read(limit_bytes + 1)
    if len(raw) > limit_bytes:
        raise ValueError("El archivo supera el límite permitido.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ValueError("El archivo debe usar codificación UTF-8.") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            "El archivo no contiene JSON válido "
            f"(línea {error.lineno}, columna {error.colno})."
        ) from error
    if not isinstance(payload, dict):
        raise ValueError("El archivo debe contener un objeto JSON.")
    return payload


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
    timezone_name = current_user.timezone or current_app.config["APP_TIMEZONE"]
    app_timezone = ZoneInfo(timezone_name)
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
            timezone_name,
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
    timezone_name = current_user.timezone or current_app.config["APP_TIMEZONE"]
    app_timezone = ZoneInfo(timezone_name)
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
        timezone_name=timezone_name,
    )
    OnboardingDismissForm,
