import json
import uuid
from zoneinfo import ZoneInfo

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.gym import gym_bp
from app.models import TrainingPlan, TrainingPlanVersion, TrainingSession
from app.services.gym_programs import (GymError, PRESETS, activate_program, catalog, confirm_program, owned_plan, preset_draft, preview_token, resolve_draft, standard_document)
from app.services.gym_sessions import complete_set, finish_session, owned_session, start_session, workout_context
from app.services.importers.routine_draft import DeterministicParser, MAX_BYTES, RoutineImportDraft, RoutineParseError, draft_from_document
from app.services.training_plans import get_active_version
from app.services.mobile_progress import progress_exercise_detail, _session_volume
from app.services.exercise_identity import normalize_exercise_name
from app.services.gym_sessions import utc


@gym_bp.app_context_processor
def exercise_media_context():
    # Lazy: only Gym templates request the owner-scoped presentation projection.
    projection = None
    def binding(exercise):
        nonlocal projection
        if projection is None:
            from app.services.gym_media import media_catalog, media_projection
            projection = media_projection(catalog(current_user.id), media_catalog())
        return projection(exercise)
    return {"media_binding": binding}


@gym_bp.errorhandler(GymError)
def handle_gym_error(error):
    db.session.rollback()
    if request.is_json:
        return jsonify(error=str(error)), error.status
    return render_template("gym/error.html", message=str(error)), error.status


@gym_bp.before_request
def bounded_request():
    if request.content_length and request.content_length > 3 * MAX_BYTES:
        abort(413)


def program_home():
    plans = db.session.execute(db.select(TrainingPlan).where(TrainingPlan.user_id == current_user.id).options(selectinload(TrainingPlan.versions)).order_by(TrainingPlan.gym_active.desc(), TrainingPlan.updated_at.desc())).scalars().all()
    ongoing = db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id == current_user.id, TrainingSession.status == "in_progress", TrainingSession.deleted_at.is_(None)).order_by(TrainingSession.started_at.desc())).scalars().all()
    last_rows = db.session.execute(db.select(TrainingSession.training_plan_version_id, TrainingSession.planned_week_number, TrainingSession.planned_day_number, db.func.max(TrainingSession.performed_at)).where(TrainingSession.user_id == current_user.id, TrainingSession.status == "completed", TrainingSession.deleted_at.is_(None)).group_by(TrainingSession.training_plan_version_id, TrainingSession.planned_week_number, TrainingSession.planned_day_number)).all()
    local_zone = ZoneInfo(current_user.timezone or "UTC")
    last = {(v, w, d): utc(moment).astimezone(local_zone) for v, w, d, moment in last_rows}
    identities = {name: item.public_id for item in catalog(current_user.id) for name in [item.normalized_name, *(alias.normalized_name for alias in item.aliases)]}
    cards = []
    for plan in plans:
        version = next((v for v in plan.versions if v.version_number == plan.active_version_number), None)
        cards.append({"plan": plan, "version": version, "days": [{"week": week["week_number"], "day": day, "last": last.get((version.id, week["week_number"], day["day_number"])), "submission": str(uuid.uuid4())} for week in version.content["data"]["weeks"] for day in week["days"]] if version else []})
    return render_template("gym/programs.html", cards=cards, ongoing=ongoing, identities=identities, normalize_name=normalize_exercise_name)


@gym_bp.get("")
@login_required
def index():
    return redirect(url_for("training.list_plans"))


def _draft_from_form():
    raw = json.loads(request.form["draft"])
    if not isinstance(raw, dict) or set(raw) - {"program", "days", "warnings", "unresolved", "source_sha256", "source_ref", "source_filename"}:
        raise GymError("Borrador inválido.")
    return RoutineImportDraft(**raw)


@gym_bp.post("/programs/edit-draft")
@login_required
def edit_draft():
    try:
        draft = _draft_from_form()
        resolve_draft(draft, current_user.id)
        plan = owned_plan(current_user.id, request.form["plan_id"]) if request.form.get("plan_id") else None
        revision = int(request.form["base_revision"]) if plan else None
    except (ValueError, TypeError, KeyError):
        abort(400)
    return render_template("gym/editor.html", draft=draft, plan=plan, base_revision=revision, presets=PRESETS, identities=catalog(current_user.id))


@gym_bp.route("/programs/new", methods=["GET", "POST"])
@gym_bp.route("/programs/<public_id>/edit", methods=["GET", "POST"])
@login_required
def editor(public_id=None):
    plan = owned_plan(current_user.id, public_id) if public_id else None
    draft = draft_from_document(get_active_version(plan, current_user.id).content) if plan else RoutineImportDraft({"name": ""}, [])
    if plan:
        own_ids = {item.public_id for item in catalog(current_user.id)}
        for day in draft.days:
            for exercise in day["exercises"]:
                # Legacy/restored snapshots retain their original source references.
                # Editing resolves names against this account without rewriting history.
                if exercise.get("resolved_exercise_id") not in own_ids:
                    exercise.pop("resolved_exercise_id", None)
    source_content = None
    source_filename = None
    revision = plan.revision if plan else None
    try:
        if request.method == "POST":
            revision = int(request.form.get("base_revision") or plan.revision) if plan else None
            if request.form.get("preset"):
                draft = preset_draft(request.form["preset"])
            elif "file" in request.files and request.files["file"].filename:
                upload = request.files["file"]
                source_content, source_filename = upload.stream.read(MAX_BYTES + 1), upload.filename
                draft = DeterministicParser().parse(source_content, source_filename, request.form.get("name", ""))
            elif request.form.get("structured_text"):
                draft = DeterministicParser().parse(request.form["structured_text"].encode(), "routine.txt", request.form.get("name", ""))
            else:
                draft = _draft_from_form()
                for day_index, day in enumerate(draft.days):
                    for exercise_index, exercise in enumerate(day["exercises"]):
                        field = f"mapping_{day_index}_{exercise_index}"
                        if field in request.form:
                            value = request.form[field]
                            exercise.pop("resolved_exercise_id", None)
                            exercise.pop("name", None)
                            exercise["create_new"] = value == "new"
                            if value and value != "new":
                                exercise["resolved_exercise_id"] = value
            # A mapping or prescription edit always returns through a fresh preview.
            resolve_draft(draft, current_user.id)
            standard_document(draft, current_user.id)
            if source_content is not None:
                from app.services.gym_import_sources import stage_source
                stage_source(draft, source_content, source_filename, current_user.id)
            revision = int(request.form.get("base_revision") or plan.revision) if plan else None
            return render_template("gym/preview.html", draft=draft, plan=plan, base_revision=revision, token=preview_token(draft, current_user.id, public_id, revision), identities=catalog(current_user.id))
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        if isinstance(error, GymError) and error.status == 404:
            abort(404)
        flash("Revisa el programa: " + (str(error) if isinstance(error, (GymError, RoutineParseError)) else "formato o valores inválidos; verifica columnas, unidades y rangos."), "danger")
    return render_template("gym/editor.html", draft=draft, plan=plan, base_revision=revision, presets=PRESETS, identities=catalog(current_user.id))


@gym_bp.post("/programs/confirm")
@login_required
def confirm():
    try:
        draft = _draft_from_form()
        plan, duplicate = confirm_program(draft, current_user.id, request.form.get("token", ""), plan_id=request.form.get("plan_id") or None, base_revision=int(request.form["base_revision"]) if request.form.get("base_revision") else None)
        db.session.commit()
    except (ValueError, TypeError, KeyError) as error:
        db.session.rollback()
        return render_template("gym/error.html", message=str(error) if isinstance(error, GymError) else "No se pudo confirmar el programa; revisa un nuevo preview."), getattr(error, "status", 400)
    flash("Ese contenido ya estaba guardado." if duplicate else "Programa guardado. Tu historial conserva su versión original.", "success")
    return redirect(url_for("training.list_plans"))


@gym_bp.post("/programs/<public_id>/activate")
@login_required
def activate(public_id):
    try:
        activate_program(current_user.id, public_id)
        db.session.commit()
    except GymError as error:
        db.session.rollback()
        abort(error.status)
    return redirect(url_for("training.list_plans"))


@gym_bp.post("/programs/<public_id>/archive")
@login_required
def archive(public_id):
    plan = owned_plan(current_user.id, public_id, lock=True)
    plan.status = "archived"
    plan.gym_active = False
    db.session.commit()
    return redirect(url_for("training.list_plans"))


@gym_bp.route("/programs/<public_id>/delete", methods=["GET", "POST"])
@login_required
def delete(public_id):
    from app.services.gym_delete import delete_program, deletion_blocker
    if request.method == "GET":
        plan = owned_plan(current_user.id, public_id)
        return render_template("gym/delete.html", plan=plan, blocker=deletion_blocker(plan))
    try:
        revision = int(request.form.get("base_revision", ""))
    except (ValueError, TypeError):
        raise GymError("Revisión inválida.", 400)
    try:
        deleted = delete_program(current_user.id, public_id, base_revision=revision,
                                 confirmation=request.form.get("confirmation"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    flash("Rutina eliminada." if deleted else "La rutina ya estaba eliminada.", "success")
    return redirect(url_for("training.list_plans"), code=303)


@gym_bp.post("/programs/<public_id>/start")
@login_required
def start(public_id):
    try:
        record = start_session(current_user.id, public_id, request.form.get("version_id"), int(request.form.get("week", "0")), int(request.form.get("day", "0")), request.form.get("submission_id"))
        db.session.commit()
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return render_template("gym/error.html", message=str(error) if isinstance(error, GymError) else "Inicio inválido."), getattr(error, "status", 400)
    return redirect(url_for("gym.workout", public_id=record.public_id))


@gym_bp.get("/sessions/<public_id>")
@login_required
def workout(public_id):
    try:
        record = owned_session(current_user.id, public_id)
        context = workout_context(record, current_user.id, current_user.preferred_load_unit or "kg")
    except GymError as error:
        abort(error.status)
    volume, partial = _session_volume(record)
    if volume is not None and context["unit"] == "lb":
        from app.services.workout_loads import from_kg
        volume = from_kg(volume, "lb")
    previous_volume = sum((float(s["previous"]["load"]) * s["previous"]["reps"] for ex in context["exercises"] for s in ex["sets"] if s["previous"].get("load") is not None), 0)
    return render_template("gym/workout.html", record=record, context=context, volume=round(volume, 2) if volume is not None else None, partial=partial, previous_volume=round(previous_volume, 2) if previous_volume else None)


@gym_bp.post("/sessions/<public_id>/sets/<int:exercise_order>/<int:set_number>")
@login_required
def save_set(public_id, exercise_order, set_number):
    try:
        values = request.get_json() if request.is_json else {key: request.form[key] for key in ("load", "unit", "reps", "rir", "rpe") if key in request.form}
        if not isinstance(values, dict):
            raise GymError("Serie inválida.")
        record, training_set, duplicate = complete_set(current_user.id, public_id, exercise_order, set_number, values)
        db.session.commit()
    except (ValueError, TypeError, KeyError) as error:
        db.session.rollback()
        message = str(error) if isinstance(error, GymError) else "Revisa los valores de la serie."
        if request.is_json:
            return jsonify(error=message), getattr(error, "status", 400)
        return render_template("gym/error.html", message=message), getattr(error, "status", 400)
    if request.is_json:
        return jsonify(saved=True, duplicate=duplicate, revision=record.revision, rest_seconds=training_set.rest_seconds)
    return redirect(url_for("gym.workout", public_id=public_id))


@gym_bp.post("/sessions/<public_id>/finish")
@login_required
def finish(public_id):
    try:
        record = finish_session(current_user.id, public_id, request.form.get("status"))
        db.session.commit()
    except GymError as error:
        db.session.rollback()
        return render_template("gym/error.html", message=str(error)), error.status
    return redirect(url_for("gym.workout", public_id=record.public_id))


@gym_bp.get("/exercises/<public_id>/progress")
@login_required
def exercise_progress(public_id):
    try:
        progress = progress_exercise_detail(current_user.id, public_id, "365")
    except ValueError as error:
        abort(getattr(error, "status", 404))
    return render_template("gym/progress.html", progress=progress)
