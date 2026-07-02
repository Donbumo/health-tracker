from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import TrainingSession
from app.services.exporters.training_session import (
    TrainingSessionCsvExporter,
    TrainingSessionHtmlExporter,
    TrainingSessionJsonExporter,
)
from app.services.files import UploadError, store_uploaded_file
from app.services.importers.base import ImporterError
from app.services.importers.completed_workout import import_completed_workout_file
from app.services.manual_json import ManualJsonGenerationError
from app.services.validation import JsonSchemaValidationError
from app.services.workout_sessions import (
    PlannedDay,
    TrainingSessionError,
    compare_plan_to_session,
    create_manual_training_session,
    list_planned_days,
    resolve_planned_day,
)
from app.sessions import sessions_bp
from app.sessions.forms import CompletedWorkoutImportForm, TrainingSessionForm


SESSION_EXPORTERS = {
    "json": TrainingSessionJsonExporter(),
    "csv": TrainingSessionCsvExporter(),
    "html": TrainingSessionHtmlExporter(),
}


def _user_session_or_404(session_id: int) -> TrainingSession:
    session = db.session.execute(
        db.select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if session is None:
        abort(404)
    return session


def _decimal_value(value: str, label: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise TrainingSessionError(f"{label} must be a number") from error
    if not number.is_finite() or number < minimum or number > maximum:
        raise TrainingSessionError(f"{label} is outside the allowed range")
    return number


def _actual_exercises(planned_day: PlannedDay) -> list[dict]:
    actual_exercises = []
    for exercise_index, planned_exercise in enumerate(planned_day.day["exercises"]):
        completed_sets = []
        for set_index, planned_set in enumerate(planned_exercise["sets"]):
            prefix = f"exercise_{exercise_index}_set_{set_index}"
            if request.form.get(f"{prefix}_completed") != "1":
                continue

            weight = _decimal_value(
                request.form.get(f"{prefix}_weight_kg", ""),
                "Weight",
                Decimal("0"),
                Decimal("2000"),
            )
            reps_value = _decimal_value(
                request.form.get(f"{prefix}_reps", ""),
                "Reps",
                Decimal("1"),
                Decimal("10000"),
            )
            if reps_value != reps_value.to_integral_value():
                raise TrainingSessionError("Reps must be a whole number")

            set_data = {
                "set_number": len(completed_sets) + 1,
                "planned_set_number": planned_set["set_number"],
                "weight_kg": float(weight),
                "reps": int(reps_value),
            }
            rir_value = request.form.get(f"{prefix}_rir", "").strip()
            if rir_value:
                set_data["rir"] = float(
                    _decimal_value(
                        rir_value,
                        "RIR",
                        Decimal("0"),
                        Decimal("10"),
                    )
                )
            notes = request.form.get(f"{prefix}_notes", "").strip()
            if len(notes) > 2000:
                raise TrainingSessionError("Set notes are too long")
            if notes:
                set_data["notes"] = notes
            completed_sets.append(set_data)

        if completed_sets:
            actual_exercises.append(
                {
                    "exercise_order": len(actual_exercises) + 1,
                    "planned_exercise_order": planned_exercise["exercise_order"],
                    "name": planned_exercise["name"],
                    "sets": completed_sets,
                }
            )
    return actual_exercises


@sessions_bp.get("")
@login_required
def list_sessions():
    sessions = db.session.execute(
        db.select(TrainingSession)
        .where(TrainingSession.user_id == current_user.id)
        .order_by(TrainingSession.performed_at.desc())
    ).scalars()
    return render_template("sessions/list.html", sessions=sessions)


@sessions_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_session():
    form = CompletedWorkoutImportForm()
    if form.validate_on_submit():
        try:
            source_file, _file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            training_session, duplicate = import_completed_workout_file(
                source_file,
                current_user.id,
            )
        except (
            ImporterError,
            JsonSchemaValidationError,
            TrainingSessionError,
            UploadError,
        ) as error:
            flash(f"No fue posible importar la sesión: {error}", "danger")
        else:
            if duplicate:
                flash("Esta sesión ya había sido importada.", "warning")
            else:
                flash("Sesión JSON importada correctamente.", "success")
            return redirect(
                url_for("sessions.detail", session_id=training_session.id)
            )
    return render_template("sessions/import.html", form=form)


@sessions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_session():
    plan_id = request.args.get("plan_id", type=int)
    options = list_planned_days(current_user.id, plan_id=plan_id)
    selected_key = request.values.get("planned_day", "")
    selected_day = None
    if selected_key:
        try:
            selected_day = resolve_planned_day(selected_key, current_user.id)
        except TrainingSessionError as error:
            flash(str(error), "danger")

    form = TrainingSessionForm()
    if not form.is_submitted() and selected_day is not None:
        app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        form.planned_day.data = selected_day.key
        form.performed_at.data = datetime.now(app_timezone).replace(
            tzinfo=None,
            second=0,
            microsecond=0,
        )

    if form.validate_on_submit() and selected_day is not None:
        app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        performed_at = form.performed_at.data.replace(tzinfo=app_timezone)
        try:
            session, duplicate = create_manual_training_session(
                user_id=current_user.id,
                planned_day=selected_day,
                performed_at=performed_at,
                exercises=_actual_exercises(selected_day),
                notes=form.notes.data,
            )
        except (
            JsonSchemaValidationError,
            ManualJsonGenerationError,
            TrainingSessionError,
        ) as error:
            flash(f"No fue posible guardar la sesión: {error}", "danger")
        else:
            if duplicate:
                flash("Esta sesión ya estaba registrada.", "warning")
            else:
                flash("Sesión registrada correctamente.", "success")
            return redirect(url_for("sessions.detail", session_id=session.id))

    return render_template(
        "sessions/new.html",
        form=form,
        options=options,
        selected_day=selected_day,
        plan_id=plan_id,
        timezone_name=current_app.config["APP_TIMEZONE"],
    )


@sessions_bp.get("/<int:session_id>")
@login_required
def detail(session_id: int):
    session = _user_session_or_404(session_id)
    comparison = compare_plan_to_session(session)
    return render_template(
        "sessions/detail.html",
        session=session,
        comparison=comparison,
    )


@sessions_bp.get("/<int:session_id>/export/<string:format_name>")
@login_required
def export_format(session_id: int, format_name: str):
    training_session = _user_session_or_404(session_id)
    exporter = SESSION_EXPORTERS.get(format_name)
    if exporter is None:
        abort(404)
    artifact = exporter.export(training_session, current_user.id)
    plan_name = secure_filename(training_session.training_plan.name)
    filename_base = plan_name or f"training_session_{training_session.id}"
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=not artifact.inline,
        download_name=(
            f"{filename_base}_session_{training_session.id}.{artifact.extension}"
        ),
    )
