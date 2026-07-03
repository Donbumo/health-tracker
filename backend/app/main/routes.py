from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.main import main_bp
from app.main.forms import UploadForm, WeighInForm
from app.models import UploadedFile
from app.services.files import UploadError, store_uploaded_file
from app.services.files import mark_import_status
from app.services.daily_dashboard import daily_health_dashboard
from app.services.importers.weigh_in import WeighInImportError, import_weigh_in_file
from app.services.manual_json import (
    ManualJsonGenerationError,
    build_weigh_in_document,
    generate_standard_json,
)
from app.services.validation import JsonSchemaValidationError


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
