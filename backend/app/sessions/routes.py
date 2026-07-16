from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zoneinfo import ZoneInfo
import uuid

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
from sqlalchemy.orm import selectinload

from app.models import PlannedWorkout, TrainingPlan, TrainingSession, TrainingSessionExercise
from app.services.exporters.training_session import (
    TrainingSessionCsvExporter,
    TrainingSessionHtmlExporter,
    TrainingSessionJsonExporter,
)
from app.services.files import UploadError, mark_import_status, store_uploaded_file
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
    resolve_planned_workout_day,
    resolve_session_planned_day,
    update_manual_training_session,
)
from app.services.workout_drafts import latest_context_draft, serialize_draft
from app.services.workout_loads import (
    MODE_COMPONENTS,
    LOAD_MODE_LABELS,
    COMPONENT_LABELS,
    SUPPORTED_MODES,
    SUPPORTED_UNITS,
    WorkoutLoadError,
    calculate_workout_load,
    load_entry_defaults,
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

            load_mode = request.form.get(f"{prefix}_load_mode", "direct_total")
            load_unit = request.form.get(f"{prefix}_load_unit", "kg")
            component_names = MODE_COMPONENTS.get(load_mode)
            if component_names is None:
                raise TrainingSessionError("Unsupported load mode")
            components = {
                name: {
                    "value": request.form.get(f"{prefix}_load_{name}", ""),
                    "unit": (
                        "s"
                        if name == "duration_seconds"
                        else "m"
                        if name == "distance_meters"
                        else request.form.get(
                            f"{prefix}_load_{name}_unit", load_unit
                        )
                    ),
                }
                for name in component_names
            }
            if load_mode == "direct_total" and not components["direct_total"]["value"]:
                components["direct_total"]["value"] = request.form.get(
                    f"{prefix}_weight_kg", ""
                )
            try:
                load = calculate_workout_load(load_mode, load_unit, components)
            except WorkoutLoadError as error:
                raise TrainingSessionError(str(error)) from error
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
                "weight_kg": float(load.weight_kg),
                "load_details": load.details,
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
            rpe_value = request.form.get(f"{prefix}_rpe", "").strip()
            if rpe_value:
                set_data["rpe"] = float(
                    _decimal_value(
                        rpe_value,
                        "RPE",
                        Decimal("1"),
                        Decimal("10"),
                    )
                )
            rest_value = request.form.get(f"{prefix}_rest_seconds", "").strip()
            if rest_value:
                rest_seconds = _decimal_value(
                    rest_value,
                    "Rest seconds",
                    Decimal("0"),
                    Decimal("86400"),
                )
                if rest_seconds != rest_seconds.to_integral_value():
                    raise TrainingSessionError("Rest seconds must be a whole number")
                set_data["rest_seconds"] = int(rest_seconds)
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
    page = _positive_int(request.args.get("page"), 1)
    per_page = 20
    statement = db.select(TrainingSession).where(
        TrainingSession.user_id == current_user.id,
        TrainingSession.deleted_at.is_(None),
    )
    date_from = _filter_date(request.args.get("date_from"), "fecha inicial")
    date_to = _filter_date(request.args.get("date_to"), "fecha final")
    timezone_name = current_user.timezone or current_app.config["APP_TIMEZONE"]
    local_timezone = ZoneInfo(timezone_name)
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=local_timezone)
        statement = statement.where(TrainingSession.performed_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to, time.max, tzinfo=local_timezone)
        statement = statement.where(TrainingSession.performed_at <= end)
    plan_id = _positive_int(request.args.get("plan_id"), 0)
    if plan_id:
        statement = statement.where(TrainingSession.training_plan_id == plan_id)
    exercise = (request.args.get("exercise") or "").strip()
    if exercise:
        statement = statement.where(
            TrainingSession.exercises.any(
                TrainingSessionExercise.name.ilike(f"%{exercise[:200]}%")
            )
        )
    total = db.session.execute(
        db.select(db.func.count()).select_from(statement.order_by(None).subquery())
    ).scalar_one()
    sessions = db.session.execute(
        statement.options(
            selectinload(TrainingSession.training_plan),
            selectinload(TrainingSession.training_plan_version),
        )
        .order_by(TrainingSession.performed_at.desc(), TrainingSession.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    ).scalars().all()
    plans = db.session.execute(
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == current_user.id)
        .order_by(TrainingPlan.name)
    ).scalars().all()
    return render_template(
        "sessions/list.html",
        sessions=sessions,
        plans=plans,
        page=page,
        has_previous=page > 1,
        has_next=page * per_page < total,
        total=total,
        filters={
            "date_from": request.args.get("date_from", ""),
            "date_to": request.args.get("date_to", ""),
            "plan_id": plan_id,
            "exercise": exercise,
        },
    )


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _filter_date(value: str | None, label: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        flash(f"La {label} no es válida y se ignoró.", "warning")
        return None


@sessions_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_session():
    form = CompletedWorkoutImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
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
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="completed_workout",
                    error_message=str(error),
                )
            flash(f"No fue posible importar la sesión: {error}", "danger")
        else:
            duplicate = file_duplicate or duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="completed_workout",
            )
            if duplicate:
                flash("Esta sesión ya había sido importada.", "warning")
            else:
                flash("Sesión JSON importada correctamente.", "success")
            return redirect(
                url_for("sessions.detail", session_id=training_session.id)
            )
    return render_template("sessions/import.html", form=form)


def _new_session_context():
    plan_id = request.args.get("plan_id", type=int)
    options = list_planned_days(current_user.id, plan_id=plan_id)
    planned_public_id = request.values.get("planned_workout_id", "").strip()
    planned_workout = None
    if planned_public_id:
        planned_workout = db.session.execute(
            db.select(PlannedWorkout).where(
                PlannedWorkout.user_id == current_user.id,
                PlannedWorkout.public_id == planned_public_id,
                PlannedWorkout.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if planned_workout is None:
            abort(404)
    selected_key = request.values.get("planned_day", "")
    selected_day = None
    if planned_workout is not None:
        try:
            selected_day = resolve_planned_workout_day(
                planned_workout, current_user.id
            )
        except TrainingSessionError as error:
            flash(str(error), "danger")
    elif selected_key:
        try:
            selected_day = resolve_planned_day(selected_key, current_user.id)
        except TrainingSessionError as error:
            flash(str(error), "danger")
    return plan_id, options, selected_day, planned_workout


def _server_draft(selected_day, planned_workout):
    if selected_day is None:
        return None
    draft = latest_context_draft(
        user_id=current_user.id,
        version_id=selected_day.version.id,
        week_number=selected_day.week["week_number"],
        day_number=selected_day.day["day_number"],
        planned_workout_id=planned_workout.id if planned_workout else None,
    )
    return serialize_draft(draft, include_payload=True) if draft else None


def _template_context(
    form,
    plan_id,
    options,
    selected_day,
    planned_workout,
    *,
    form_values=None,
    drafts_enabled=True,
    editing_session=None,
):
    exercise_names = (
        [item["name"] for item in selected_day.day["exercises"]]
        if selected_day is not None
        else []
    )
    return {
        "form": form,
        "options": options,
        "selected_day": selected_day,
        "planned_workout": planned_workout,
        "plan_id": plan_id,
        "timezone_name": current_app.config["APP_TIMEZONE"],
        "server_draft": (
            _server_draft(selected_day, planned_workout) if drafts_enabled else None
        ),
        "user_public_id": current_user.public_id,
        "preferred_load_unit": current_user.preferred_load_unit,
        "load_modes": SUPPORTED_MODES,
        "load_units": SUPPORTED_UNITS,
        "load_components": MODE_COMPONENTS,
        "load_mode_labels": LOAD_MODE_LABELS,
        "load_component_labels": COMPONENT_LABELS,
        "load_defaults": load_entry_defaults(current_user.id, exercise_names),
        "draft_max_bytes": current_app.config["WORKOUT_DRAFT_MAX_BYTES"],
        "draft_ttl_days": current_app.config["WORKOUT_DRAFT_TTL_DAYS"],
        "draft_server_debounce_ms": current_app.config[
            "WORKOUT_DRAFT_SERVER_DEBOUNCE_MS"
        ],
        "form_values": form_values if form_values is not None else request.form,
        "drafts_enabled": drafts_enabled,
        "editing_session": editing_session,
    }


def _session_edit_form_values(session: TrainingSession) -> dict[str, str]:
    values: dict[str, str] = {}
    actual_exercises = {
        item.planned_exercise_order: item for item in session.exercises
    }
    planned_day = resolve_session_planned_day(session, current_user.id)
    for exercise_index, planned_exercise in enumerate(planned_day.day["exercises"]):
        actual_exercise = actual_exercises.get(planned_exercise["exercise_order"])
        if actual_exercise is None:
            continue
        actual_sets = {
            item.planned_set_number: item for item in actual_exercise.sets
        }
        for set_index, planned_set in enumerate(planned_exercise["sets"]):
            actual_set = actual_sets.get(planned_set["set_number"])
            if actual_set is None:
                continue
            prefix = f"exercise_{exercise_index}_set_{set_index}"
            values[f"{prefix}_completed"] = "1"
            details = actual_set.load_details_json or {
                "load_mode": "direct_total",
                "original_unit": "kg",
                "components": {
                    "direct_total": {"value": str(actual_set.weight_kg), "unit": "kg"}
                },
            }
            mode = details.get("load_mode", details.get("mode", "direct_total"))
            default_unit = details.get(
                "original_unit", details.get("unit", current_user.preferred_load_unit)
            )
            values[f"{prefix}_load_mode"] = mode
            values[f"{prefix}_load_unit"] = default_unit
            for name, component in details.get("components", {}).items():
                if isinstance(component, dict):
                    values[f"{prefix}_load_{name}"] = str(component.get("value", ""))
                    values[f"{prefix}_load_{name}_unit"] = str(
                        component.get("unit", default_unit)
                    )
                else:
                    values[f"{prefix}_load_{name}"] = str(component)
                    values[f"{prefix}_load_{name}_unit"] = default_unit
            values[f"{prefix}_weight_kg"] = str(actual_set.weight_kg)
            values[f"{prefix}_reps"] = str(actual_set.reps)
            for field in ("rir", "rpe", "rest_seconds", "notes"):
                value = getattr(actual_set, field)
                if value is not None:
                    values[f"{prefix}_{field}"] = str(value)
    return values


def render_csrf_recovery(*, request_id: str):
    plan_id, options, selected_day, planned_workout = _new_session_context()
    form = TrainingSessionForm()
    context = _template_context(
        form, plan_id, options, selected_day, planned_workout
    )
    context.update(
        recovery_message=(
            "El token de seguridad venció. Recuperamos todos tus datos; "
            "vuelve a presionar Guardar."
        ),
        request_id=request_id,
    )
    return render_template("sessions/new.html", **context), 422


def render_edit_csrf_recovery(*, session_id: int, request_id: str):
    training_session = _user_session_or_404(session_id)
    selected_day = resolve_session_planned_day(training_session, current_user.id)
    form = TrainingSessionForm()
    context = _template_context(
        form,
        training_session.training_plan_id,
        [selected_day],
        selected_day,
        training_session.planned_workout,
        form_values=request.form,
        drafts_enabled=False,
        editing_session=training_session,
    )
    context.update(
        recovery_message=(
            "El token de seguridad venciÃ³. Recuperamos todos tus datos; "
            "vuelve a presionar Guardar cambios."
        ),
        request_id=request_id,
    )
    return render_template("sessions/new.html", **context), 422


@sessions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_session():
    plan_id, options, selected_day, planned_workout = _new_session_context()

    form = TrainingSessionForm()
    if not form.is_submitted() and selected_day is not None:
        app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        form.planned_day.data = selected_day.key
        form.planned_workout_id.data = (
            planned_workout.public_id if planned_workout else ""
        )
        form.performed_at.data = datetime.now(app_timezone).replace(
            tzinfo=None,
            second=0,
            microsecond=0,
        )

    if form.validate_on_submit() and selected_day is not None:
        app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        performed_at = form.performed_at.data.replace(tzinfo=app_timezone)
        try:
            submitted_client_id = request.form.get("client_submission_id")
            client_submission_id = (
                str(uuid.UUID(submitted_client_id))
                if submitted_client_id
                else None
            )
            completed_exercises = _actual_exercises(selected_day)
            completed_by_name = {item["name"]: item for item in completed_exercises}
            session, duplicate = create_manual_training_session(
                user_id=current_user.id,
                planned_day=selected_day,
                performed_at=performed_at,
                exercises=completed_exercises,
                duration_seconds=(
                    form.duration_minutes.data * 60
                    if form.duration_minutes.data is not None
                    else None
                ),
                average_heart_rate_bpm=form.average_heart_rate_bpm.data,
                calories_burned=form.calories_burned.data,
                notes=form.notes.data,
                client_submission_id=client_submission_id,
                planned_workout=planned_workout,
                preferred_load_unit=request.form.get("preferred_load_unit", "kg"),
                remembered_profiles=[
                    {
                        "exercise_name": planned_exercise["name"],
                        "load_details": completed_by_name[planned_exercise["name"]]["sets"][0]["load_details"],
                    }
                    for index, planned_exercise in enumerate(selected_day.day["exercises"])
                    if request.form.get(f"exercise_{index}_remember_load") == "1"
                    and planned_exercise["name"] in completed_by_name
                ],
            )
        except (
            ValueError,
            JsonSchemaValidationError,
            ManualJsonGenerationError,
            TrainingSessionError,
        ) as error:
            flash(f"No fue posible guardar la sesión: {error}", "danger")
        else:
            if duplicate:
                flash(
                    "Esta sesión ya estaba registrada; se abrió la existente.",
                    "warning",
                )
            else:
                flash("Sesión registrada correctamente.", "success")
            return redirect(
                url_for(
                    "sessions.detail",
                    session_id=session.id,
                )
            )

    context = _template_context(
        form, plan_id, options, selected_day, planned_workout
    )
    context["recovery_message"] = None
    return render_template("sessions/new.html", **context)


@sessions_bp.route("/<int:session_id>/edit", methods=["GET", "POST"])
@login_required
def edit_session(session_id: int):
    training_session = _user_session_or_404(session_id)
    selected_day = resolve_session_planned_day(training_session, current_user.id)
    form = TrainingSessionForm()
    if not form.is_submitted():
        form.planned_day.data = selected_day.key
        form.planned_workout_id.data = (
            training_session.planned_workout.public_id
            if training_session.planned_workout
            else ""
        )
        form.client_submission_id.data = (
            training_session.client_submission_id or str(uuid.uuid4())
        )
        form.performed_at.data = training_session.performed_at.replace(tzinfo=None)
        form.duration_minutes.data = (
            training_session.duration_seconds // 60
            if training_session.duration_seconds is not None
            else None
        )
        form.average_heart_rate_bpm.data = training_session.average_heart_rate_bpm
        form.calories_burned.data = training_session.calories_burned
        form.notes.data = training_session.notes

    if form.validate_on_submit():
        app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        try:
            completed_exercises = _actual_exercises(selected_day)
            completed_by_name = {item["name"]: item for item in completed_exercises}
            updated, unchanged = update_manual_training_session(
                session=training_session,
                user_id=current_user.id,
                planned_day=selected_day,
                performed_at=form.performed_at.data.replace(tzinfo=app_timezone),
                exercises=completed_exercises,
                duration_seconds=(
                    form.duration_minutes.data * 60
                    if form.duration_minutes.data is not None
                    else None
                ),
                average_heart_rate_bpm=form.average_heart_rate_bpm.data,
                calories_burned=form.calories_burned.data,
                notes=form.notes.data,
                preferred_load_unit=request.form.get("preferred_load_unit", "kg"),
                remembered_profiles=[
                    {
                        "exercise_name": planned_exercise["name"],
                        "load_details": completed_by_name[planned_exercise["name"]]["sets"][0]["load_details"],
                    }
                    for index, planned_exercise in enumerate(selected_day.day["exercises"])
                    if request.form.get(f"exercise_{index}_remember_load") == "1"
                    and planned_exercise["name"] in completed_by_name
                ],
            )
        except (
            ValueError,
            JsonSchemaValidationError,
            ManualJsonGenerationError,
            TrainingSessionError,
        ) as error:
            flash(f"No fue posible actualizar la sesiÃ³n: {error}", "danger")
        else:
            flash(
                "La sesiÃ³n no cambiÃ³." if unchanged else "SesiÃ³n actualizada correctamente.",
                "warning" if unchanged else "success",
            )
            return redirect(url_for("sessions.detail", session_id=updated.id))

    context = _template_context(
        form,
        training_session.training_plan_id,
        [selected_day],
        selected_day,
        training_session.planned_workout,
        form_values=(request.form if form.is_submitted() else _session_edit_form_values(training_session)),
        drafts_enabled=False,
        editing_session=training_session,
    )
    context["recovery_message"] = None
    return render_template("sessions/new.html", **context)


@sessions_bp.get("/<int:session_id>")
@login_required
def detail(session_id: int):
    session = _user_session_or_404(session_id)
    comparison = compare_plan_to_session(session)
    return render_template(
        "sessions/detail.html",
        session=session,
        comparison=comparison,
        saved_submission_id=session.client_submission_id,
        user_public_id=current_user.public_id,
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
