import json
import uuid
from zoneinfo import ZoneInfo

from flask import abort, flash, g, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.gym import gym_bp
from app.models import TrainingPlan, TrainingPlanVersion, TrainingSession
from app.services.gym_programs import (GymError, PRESETS, activate_program, catalog, owned_plan, preset_draft, resolve_draft, standard_document)
from app.services.gym_delete import (
    discard_pending_draft,
    discard_pending_planned,
    discard_pending_session,
    pending_artifacts,
    deletion_preview,
)
from app.services.mobile_sync import MobileSyncError
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
    references = None
    identities = None
    def owner_catalog():
        nonlocal identities
        if identities is None:
            identities = getattr(g, "strength_identities", None)
            if identities is None:
                identities = catalog(current_user.id)
        return identities
    def reference_catalog():
        nonlocal references
        if references is None:
            from app.services.exercise_catalog import external_catalog
            references = external_catalog()
        return references
    def binding(exercise):
        nonlocal projection
        if projection is None:
            from app.services.gym_media import media_catalog, media_projection
            projection = media_projection(owner_catalog(), media_catalog(), reference_catalog())
        return projection(exercise)
    def reference_candidates(name):
        from app.services.exercise_catalog import candidate_report
        return candidate_report(name, owner_catalog(), reference_catalog())
    return {"media_binding": binding, "reference_catalog": reference_catalog, "reference_candidates": reference_candidates}


@gym_bp.errorhandler(GymError)
def handle_gym_error(error):
    db.session.rollback()
    if request.is_json:
        return jsonify(error=str(error)), error.status
    return render_template("gym/error.html", message=str(error), draft_url=_draft_recovery_url()), error.status


def _draft_recovery_url():
    from app.models import GymImportDraft
    public_id = (request.view_args or {}).get('draft_id') or request.form.get('draft_id')
    if public_id and current_user.is_authenticated:
        existing = db.session.execute(db.select(GymImportDraft.public_id).where(
            GymImportDraft.public_id == public_id, GymImportDraft.user_id == current_user.id,
            GymImportDraft.state == 'pending')).scalar_one_or_none()
        if existing:
            return url_for('gym.import_draft', draft_id=existing)
    return None


@gym_bp.before_request
def bounded_request():
    if request.content_length and request.content_length > 3 * MAX_BYTES:
        abort(413)


@gym_bp.after_request
def private_gym_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def strength_reader():
    from app.services.gym_strength import StrengthReader
    reader = StrengthReader(current_user.id)
    g.strength_identities = reader.identities
    return reader


def program_home():
    reader = strength_reader()
    plans = sorted(reader.plans, key=lambda p: (p.gym_active, p.updated_at), reverse=True)
    ongoing = db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id == current_user.id, TrainingSession.status == "in_progress", TrainingSession.deleted_at.is_(None)).order_by(TrainingSession.started_at.desc())).scalars().all()
    last_rows = db.session.execute(db.select(TrainingSession.training_plan_version_id, TrainingSession.planned_week_number, TrainingSession.planned_day_number, db.func.max(TrainingSession.performed_at)).where(TrainingSession.user_id == current_user.id, TrainingSession.status == "completed", TrainingSession.deleted_at.is_(None)).group_by(TrainingSession.training_plan_version_id, TrainingSession.planned_week_number, TrainingSession.planned_day_number)).all()
    local_zone = ZoneInfo(current_user.timezone or "UTC")
    last = {(v, w, d): utc(moment).astimezone(local_zone) for v, w, d, moment in last_rows}
    identities = {name: item.public_id for name, item in reader.by_name.items() if item is not None}
    cards = []
    for plan in plans:
        version = next((v for v in plan.versions if v.version_number == plan.active_version_number), None)
        cards.append({"plan": plan, "version": version, "days": [{"week": week["week_number"], "day": day, "total_sets": sum(len(e["sets"]) for e in day["exercises"]), "last": last.get((version.id, week["week_number"], day["day_number"])), "submission": str(uuid.uuid4())} for week in version.content["data"]["weeks"] for day in week["days"]] if version else []})
    from app.services.exercise_mapping import review_items
    links, _, _ = review_items(current_user.id)
    from app.services.gym_import_drafts import pending
    response = make_response(render_template("gym/programs.html", cards=cards, ongoing=ongoing, identities=identities, normalize_name=normalize_exercise_name, pending_links=sum(not item["linked"] for item in links), import_drafts=pending(current_user.id), strength=reader.overview()))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@gym_bp.get("/exercise-links")
@login_required
def exercise_links():
    from app.services.exercise_mapping import review_items
    items, _, _ = review_items(current_user.id)
    return render_template("gym/exercise_links.html", pending=[item for item in items if not item["linked"]], linked=[item for item in items if item["linked"]])


@gym_bp.route("/exercise-links/review", methods=["GET", "POST"])
@login_required
def exercise_link_review():
    from app.models import ExerciseCatalogSource
    from app.services.exercise_catalog import media_entry
    from app.services.exercise_mapping import candidates, confirm_link, decision_token, review_target
    name = request.form.get("name", "") if request.method == "POST" else request.args.get("name", "")
    item, identities, entries = review_target(current_user.id, name)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "none":
            flash("Sin cambios. Puedes volver a revisar este ejercicio cuando quieras.", "success")
        elif action == "link":
            confirm_link(current_user.id, name, request.form.get("reference_id"), request.form.get("token", ""))
            db.session.commit()
            flash("Vínculo guardado. Se conservan el nombre de tu rutina y tu historial.", "success")
        else:
            abort(400)
        return redirect(url_for("gym.exercise_links"))
    query = request.args.get("q", "").strip()[:200]
    matches = candidates(item["name"], identities, entries, query)
    states = {state.source_id: state for state in db.session.execute(db.select(ExerciseCatalogSource)).scalars()}
    cards = [{"row": row, "media": media_entry(row, states[row.source]), "token": decision_token(current_user.id, item, row)} for row in matches[:24]]
    return render_template("gym/exercise_link_review.html", item=item, cards=cards, total=len(matches), query=query)


@gym_bp.get("")
@login_required
def index():
    return redirect(url_for("training.list_plans"))


def _draft_from_form():
    raw = json.loads(request.form["draft"])
    if not isinstance(raw, dict) or set(raw) - {"program", "days", "warnings", "unresolved", "source_sha256", "source_ref", "source_filename"}:
        raise GymError("Borrador inválido.")
    return RoutineImportDraft(**raw)


@gym_bp.get("/programs/drafts/<draft_id>")
@login_required
def import_draft(draft_id):
    from app.services import gym_import_drafts as drafts
    row = drafts.owned(current_user.id, draft_id)
    if row.state != 'pending':
        return redirect(url_for('training.list_plans'))
    draft = drafts.materialize(row)
    plan = owned_plan(current_user.id, row.target_public_id) if row.target_public_id else None
    state = drafts.status(row)
    edit = request.args.get('edit') == '1' or bool(state['error'])
    if not edit:
        resolve_draft(draft, current_user.id)
    return render_template('gym/editor.html' if edit else 'gym/preview.html',
        draft=draft, plan=plan, base_revision=row.base_revision, saved_draft=row,
        save_state=state, token=state['token'], presets=PRESETS, identities=catalog(current_user.id))


@gym_bp.post("/programs/drafts/<draft_id>/save")
@login_required
def save_import_draft(draft_id):
    from app.services import gym_import_drafts as drafts
    try:
        body = request.get_json() if request.is_json else None
        if not isinstance(body, dict) or set(body) != {'revision', 'change'} or not isinstance(body['change'], dict):
            raise GymError('Cambio inválido.')
        row = drafts.save(current_user.id, draft_id, body['revision'], body['change'])
        state = drafts.status(row)
        db.session.commit()
        return jsonify(state)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        db.session.rollback()
        if isinstance(error, GymError):
            raise
        raise GymError('No se pudo guardar. Revisa el borrador.') from error


@gym_bp.post("/programs/drafts/<draft_id>/review")
@login_required
def review_import_draft(draft_id):
    from app.services import gym_import_drafts as drafts
    row = drafts.owned(current_user.id, draft_id, lock=True)
    try:
        drafts._pending(row, int(request.form.get('revision', '')))
        draft = drafts.materialize(row)
        for di, day in enumerate(draft.days):
            for ei, exercise in enumerate(day['exercises']):
                field = f'mapping_{di}_{ei}'
                if field in request.form:
                    drafts.set_mapping(draft, di, ei, request.form[field])
        resolve_draft(draft, current_user.id)
        row = drafts.save(current_user.id, draft_id, row.revision, {'action':'edit','draft':{'program':draft.program,'days':draft.days}})
        db.session.commit()
    except (ValueError, TypeError, KeyError) as error:
        db.session.rollback()
        raise error if isinstance(error, GymError) else GymError('Revisa el borrador.')
    return redirect(url_for('gym.import_draft', draft_id=row.public_id))


@gym_bp.post("/programs/drafts/<draft_id>/cancel")
@login_required
def cancel_import_draft(draft_id):
    from app.services import gym_import_drafts as drafts
    try:
        drafts.cancel(current_user.id, draft_id, int(request.form.get('revision', '')))
        db.session.commit()
    except (ValueError, TypeError) as error:
        db.session.rollback()
        raise error if isinstance(error, GymError) else GymError('Revisión inválida.')
    flash('Importación cancelada. No se guardaron mappings personales.', 'success')
    return redirect(url_for('training.list_plans'))


@gym_bp.post("/programs/edit-draft")
@login_required
def edit_draft():
    # Compatibility for an already-open legacy preview; persist before editing.
    from app.services import gym_import_drafts as drafts
    try:
        draft = _draft_from_form()
        plan = owned_plan(current_user.id, request.form['plan_id']) if request.form.get('plan_id') else None
        revision = int(request.form['base_revision']) if plan else None
        row = drafts.create(draft, current_user.id, plan=plan, base_revision=revision)
        db.session.commit()
    except (ValueError, TypeError, KeyError):
        db.session.rollback()
        abort(400)
    return redirect(url_for('gym.import_draft', draft_id=row.public_id, edit=1))


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
                            exercise.pop("resolved_catalog_id", None)
                            exercise.pop("catalog_revision", None)
                            exercise.pop("external_source", None)
                            exercise.pop("external_id", None)
                            exercise.pop("name", None)
                            exercise["create_new"] = value == "new"
                            if value.startswith("catalog:"):
                                exercise["resolved_catalog_id"] = value.removeprefix("catalog:")
                            elif value and value != "new":
                                exercise["resolved_exercise_id"] = value
            # A mapping or prescription edit always returns through a fresh preview.
            resolve_draft(draft, current_user.id)
            standard_document(draft, current_user.id)
            from app.services import gym_import_drafts as drafts
            if request.form.get('draft_id'):
                row = drafts.owned(current_user.id, request.form['draft_id'])
                if row.target_public_id != public_id:
                    abort(404)
                row = drafts.save(current_user.id, row.public_id, int(request.form.get('revision', '')), {'action':'edit', 'draft':{'program':draft.program,'days':draft.days}})
            else:
                if source_filename:
                    draft.source_filename = str(source_filename).replace('\\', '/').rsplit('/', 1)[-1][:200]
                source_type = source_filename.rsplit('.', 1)[-1].lower() if source_filename else 'text' if request.form.get('structured_text') else 'manual'
                row = drafts.create(draft, current_user.id, plan=plan, base_revision=revision, source_type=source_type)
            db.session.commit()
            return redirect(url_for('gym.import_draft', draft_id=row.public_id))
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        db.session.rollback()
        if isinstance(error, GymError) and error.status in (404, 409):
            raise
        flash("Revisa el programa: " + (str(error) if isinstance(error, (GymError, RoutineParseError)) else "formato o valores inválidos; verifica columnas, unidades y rangos."), "danger")
    return render_template("gym/editor.html", draft=draft, plan=plan, base_revision=revision, presets=PRESETS, identities=catalog(current_user.id))


@gym_bp.post("/programs/confirm")
@login_required
def confirm():
    try:
        from app.services import gym_import_drafts as drafts
        plan, duplicate = drafts.confirm(current_user.id, request.form['draft_id'], int(request.form['revision']), request.form.get('token', ''))
        db.session.commit()
    except (ValueError, TypeError, KeyError) as error:
        db.session.rollback()
        return render_template("gym/error.html", message=str(error) if isinstance(error, GymError) else "No se pudo confirmar el programa; revisa un nuevo preview.", draft_url=_draft_recovery_url()), getattr(error, "status", 400)
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
    from app.services.gym_delete import delete_program
    if request.method == "GET":
        plan = owned_plan(current_user.id, public_id)
        return render_template("gym/delete.html", plan=plan, preview=deletion_preview(plan))
    try:
        revision = int(request.form.get("base_revision", ""))
    except (ValueError, TypeError):
        raise GymError("Revisión inválida.", 400)
    try:
        deleted = delete_program(current_user.id, public_id, base_revision=revision,
                                 confirmation=request.form.get("confirmation"),
                                 pending_token=request.form.get("pending_token"),
                                 partial_action=request.form.get("partial_action"),
                                 partial_confirmation=request.form.get("partial_confirmation"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    flash("Rutina eliminada." if deleted else "La rutina ya estaba eliminada.", "success")
    return redirect(url_for("training.list_plans"), code=303)


@gym_bp.get("/programs/<public_id>/pending")
@login_required
def pending(public_id):
    plan = owned_plan(current_user.id, public_id)
    return render_template(
        "gym/pending.html",
        plan=plan,
        pending=pending_artifacts(plan),
    )


@gym_bp.post("/programs/<public_id>/pending/<kind>/<artifact_id>/discard")
@login_required
def discard_pending(public_id, kind, artifact_id):
    confirmation = request.form.get("confirmation")
    try:
        if kind == "session":
            discard_pending_session(
                current_user.id,
                public_id,
                artifact_id,
                confirmation=confirmation,
            )
        elif kind == "planned":
            discard_pending_planned(
                current_user.id,
                public_id,
                artifact_id,
                confirmation=confirmation,
            )
        elif kind == "draft":
            discard_pending_draft(
                current_user.id,
                public_id,
                artifact_id,
                confirmation=confirmation,
            )
        else:
            raise GymError("Pendiente no reconocido.", 404)
        db.session.commit()
    except (GymError, MobileSyncError):
        db.session.rollback()
        raise
    flash("Pendiente descartado.", "success")
    return redirect(url_for("gym.pending", public_id=public_id), code=303)


@gym_bp.post("/programs/<public_id>/start")
@login_required
def start(public_id):
    try:
        record = start_session(current_user.id, public_id, request.form.get("version_id"), int(request.form.get("week", "0")), int(request.form.get("day", "0")), request.form.get("submission_id"))
        db.session.commit()
    except (ValueError, TypeError) as error:
        db.session.rollback()
        return render_template("gym/error.html", message=str(error) if isinstance(error, GymError) else "Inicio inválido."), getattr(error, "status", 400)
    return redirect(url_for("gym.completion" if record.status == "completed" else "gym.workout", public_id=record.public_id))


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
    return redirect(url_for("gym.completion" if record.status == "completed" else "gym.workout", public_id=record.public_id))


@gym_bp.get("/exercises/<public_id>/progress")
@login_required
def exercise_progress(public_id):
    progress = strength_reader().detail(public_id, request.args.get("period", "8"),
                                        program_id=request.args.get("program"), prescription_id=request.args.get("prescription"))
    return render_template("gym/progress.html", progress=progress)


@gym_bp.get("/sessions/<public_id>/summary")
@login_required
def completion(public_id):
    return render_template("gym/completion.html", summary=strength_reader().summary(public_id))


@gym_bp.get("/programs/<public_id>/progression/<prescription_id>/preview")
@login_required
def progression_preview(public_id, prescription_id):
    from app.services.gym_progression_confirm import preview
    return render_template("gym/progression_preview.html", preview=preview(current_user.id, public_id, prescription_id))


@gym_bp.post("/progression/confirm")
@login_required
def progression_confirm():
    from app.services.gym_progression_confirm import confirm
    plan, duplicate = confirm(current_user.id, request.form.get("token"))
    db.session.commit()
    flash("Este cambio ya estaba confirmado." if duplicate else "Cambio confirmado. Tu próxima sesión usará la nueva revisión.", "success")
    return redirect(url_for("training.list_plans"))
