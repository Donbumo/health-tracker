import copy
from io import BytesIO

from flask import abort, flash, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import TrainingPlan, TrainingPlanVersion
from app.services.exporters.training_plan import (
    TrainingPlanCsvExporter,
    TrainingPlanJsonExporter,
)
from app.services.files import UploadError, mark_import_status, store_uploaded_file
from app.services.importers.training_plan import import_training_plan_file
from app.services.importers.standard_import_executor import (
    StandardImportError,
    StandardImportExecutor,
)
from app.services.training_plans import (
    TrainingPlanImportError,
    activate_training_plan_version,
    create_training_plan_version,
    get_active_version,
    list_training_plan_versions,
)
from app.services.validation import JsonSchemaValidationError
from app.training import training_bp
from app.training.forms import (
    ActivateTrainingPlanVersionForm,
    DuplicateTrainingPlanForm,
    TrainingPlanCreateForm,
    TrainingPlanImportForm,
    TrainingPlanVersionForm,
)


PLAN_EXPORTERS = {
    "json": TrainingPlanJsonExporter(),
    "csv": TrainingPlanCsvExporter(),
}


def _user_plan_or_404(plan_id: int) -> TrainingPlan:
    plan = db.session.execute(
        db.select(TrainingPlan).where(
            TrainingPlan.id == plan_id,
            TrainingPlan.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if plan is None:
        abort(404)
    return plan


def _user_version_or_404(
    plan: TrainingPlan,
    version_id: int,
) -> TrainingPlanVersion:
    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.id == version_id,
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if version is None:
        abort(404)
    return version


@training_bp.get("")
@login_required
def list_plans():
    plans = db.session.execute(
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == current_user.id)
        .order_by(TrainingPlan.updated_at.desc())
    ).scalars().all()
    return render_template(
        "training/list.html",
        plans=plans,
        plan_summaries={plan.id: _plan_summary(plan) for plan in plans},
    )


@training_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_plan():
    form = TrainingPlanCreateForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        existing = db.session.execute(
            db.select(TrainingPlan).where(
                TrainingPlan.user_id == current_user.id,
                TrainingPlan.name == name,
            )
        ).scalar_one_or_none()
        if existing is not None:
            form.name.errors.append("Ya tienes una rutina con este nombre.")
        else:
            document = _guided_plan_document(form, current_user.id)
            try:
                result = StandardImportExecutor().commit_documents(
                    [document],
                    user_id=current_user.id,
                    target_type="training_plan",
                    confirmed=True,
                    audit_payload=document,
                    audit_metadata={
                        "route": "/training-plans/new",
                        "mode": "guided_manual",
                        "document_count": 1,
                    },
                )
            except StandardImportError as error:
                flash(f"No fue posible crear la rutina: {error}", "danger")
            else:
                if result["committed"]:
                    plan = db.session.execute(
                        db.select(TrainingPlan).where(
                            TrainingPlan.user_id == current_user.id,
                            TrainingPlan.name == name,
                        )
                    ).scalar_one()
                    flash("Rutina creada. Puedes añadir cambios como una nueva versión.", "success")
                    return redirect(url_for("training.detail", plan_id=plan.id))
                flash("La rutina no se creó; revisa los campos.", "danger")
    return render_template("training/create.html", form=form)


@training_bp.post("/<int:plan_id>/duplicate")
@login_required
def duplicate_plan(plan_id: int):
    plan = _user_plan_or_404(plan_id)
    form = DuplicateTrainingPlanForm()
    if not form.validate_on_submit():
        flash("Indica un nombre válido para la copia.", "danger")
        return redirect(url_for("training.detail", plan_id=plan.id))
    name = form.name.data.strip()
    if db.session.execute(
        db.select(TrainingPlan.id).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.name == name,
        )
    ).scalar_one_or_none() is not None:
        flash("Ya tienes una rutina con ese nombre.", "danger")
        return redirect(url_for("training.detail", plan_id=plan.id))
    active_version = get_active_version(plan, current_user.id)
    document = copy.deepcopy(active_version.content)
    document["user_id"] = current_user.id
    document["source_type"] = "manual_generated"
    document["data"]["name"] = name
    try:
        result = StandardImportExecutor().commit_documents(
            [document],
            user_id=current_user.id,
            target_type="training_plan",
            confirmed=True,
            audit_payload=document,
            audit_metadata={
                "route": "/training-plans/<plan>/duplicate",
                "mode": "duplicate",
                "document_count": 1,
            },
        )
    except StandardImportError as error:
        flash(f"No fue posible duplicar la rutina: {error}", "danger")
        return redirect(url_for("training.detail", plan_id=plan.id))
    if not result["committed"]:
        flash("No fue posible duplicar la rutina.", "danger")
        return redirect(url_for("training.detail", plan_id=plan.id))
    duplicate = db.session.execute(
        db.select(TrainingPlan).where(
            TrainingPlan.user_id == current_user.id,
            TrainingPlan.name == name,
        )
    ).scalar_one()
    flash("Rutina duplicada como una copia independiente.", "success")
    return redirect(url_for("training.detail", plan_id=duplicate.id))


@training_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_plan():
    form = TrainingPlanImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            plan, plan_duplicate = import_training_plan_file(
                source_file,
                current_user.id,
            )
        except (UploadError, TrainingPlanImportError, JsonSchemaValidationError) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="training_plan",
                    error_message=str(error),
                )
            flash(f"No fue posible importar la rutina: {error}", "danger")
        else:
            duplicate = file_duplicate or plan_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="training_plan",
            )
            if duplicate:
                flash("Esta rutina ya había sido importada.", "warning")
            else:
                flash("Rutina importada como versión 1.", "success")
            return redirect(url_for("training.detail", plan_id=plan.id))

    return render_template("training/import.html", form=form)


@training_bp.get("/<int:plan_id>")
@login_required
def detail(plan_id: int):
    plan = _user_plan_or_404(plan_id)
    active_version = get_active_version(plan, current_user.id)
    return render_template(
        "training/detail.html",
        plan=plan,
        active_version=active_version,
        summary=_plan_summary(plan),
        duplicate_form=DuplicateTrainingPlanForm(name=f"Copia de {plan.name}"),
    )


@training_bp.get("/<int:plan_id>/versions")
@login_required
def version_history(plan_id: int):
    plan = _user_plan_or_404(plan_id)
    versions = list_training_plan_versions(plan, current_user.id)
    return render_template(
        "training/versions.html",
        plan=plan,
        versions=versions,
        activate_form=ActivateTrainingPlanVersionForm(),
    )


@training_bp.route("/<int:plan_id>/versions/new", methods=["GET", "POST"])
@login_required
def new_version(plan_id: int):
    plan = _user_plan_or_404(plan_id)
    form = TrainingPlanVersionForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            version, duplicate = create_training_plan_version(
                plan=plan,
                source_file=source_file,
                user_id=current_user.id,
                change_reason=form.change_reason.data,
            )
        except (UploadError, TrainingPlanImportError, JsonSchemaValidationError) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="training_plan",
                    error_message=str(error),
                )
            flash(f"No fue posible crear la versión: {error}", "danger")
        else:
            duplicate = file_duplicate or duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="training_plan",
            )
            if duplicate:
                flash(
                    f"Ese contenido ya existe como versión {version.version_number}.",
                    "warning",
                )
            else:
                flash(
                    f"Versión {version.version_number} creada; la versión activa no cambió.",
                    "success",
                )
            return redirect(url_for("training.version_history", plan_id=plan.id))
    return render_template("training/new_version.html", plan=plan, form=form)


@training_bp.post("/<int:plan_id>/versions/<int:version_id>/activate")
@login_required
def activate_version(plan_id: int, version_id: int):
    plan = _user_plan_or_404(plan_id)
    version = _user_version_or_404(plan, version_id)
    form = ActivateTrainingPlanVersionForm()
    if not form.validate_on_submit():
        abort(400)
    activate_training_plan_version(
        plan=plan,
        version_id=version.id,
        user_id=current_user.id,
    )
    flash(f"Versión {version.version_number} activada.", "success")
    return redirect(url_for("training.version_history", plan_id=plan.id))


@training_bp.get("/<int:plan_id>/export")
@login_required
def export_active(plan_id: int):
    return _export_plan(plan_id, "json")


@training_bp.get("/<int:plan_id>/export/<string:format_name>")
@login_required
def export_format(plan_id: int, format_name: str):
    return _export_plan(plan_id, format_name)


def _export_plan(plan_id: int, format_name: str):
    plan = _user_plan_or_404(plan_id)
    exporter = PLAN_EXPORTERS.get(format_name)
    if exporter is None:
        abort(404)
    active_version = get_active_version(plan, current_user.id)
    artifact = exporter.export(plan, current_user.id)
    filename_base = secure_filename(plan.name) or f"training_plan_{plan.id}"
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=(
            f"{filename_base}_v{active_version.version_number}.{artifact.extension}"
        ),
    )


def _guided_plan_document(form: TrainingPlanCreateForm, user_id: int) -> dict:
    planned_sets = []
    for set_number in range(1, form.set_count.data + 1):
        planned_set = {"set_number": set_number, "reps": form.target_reps.data}
        if form.rest_seconds.data is not None:
            planned_set["rest_seconds"] = form.rest_seconds.data
        planned_sets.append(planned_set)
    data = {
        "name": form.name.data.strip(),
        "weeks": [
            {
                "week_number": 1,
                "days": [
                    {
                        "day_number": 1,
                        "name": form.day_name.data.strip(),
                        "exercises": [
                            {
                                "exercise_order": 1,
                                "name": form.exercise_name.data.strip(),
                                "sets": planned_sets,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    if form.description.data and form.description.data.strip():
        data["description"] = form.description.data.strip()
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": data,
    }


def _plan_summary(plan: TrainingPlan) -> dict:
    try:
        version = next(
            item for item in plan.versions
            if item.version_number == plan.active_version_number
        )
    except StopIteration:
        return {"weeks": 0, "days": 0, "exercises": 0, "exercise_names": []}
    weeks = version.content.get("data", {}).get("weeks", [])
    days = [day for week in weeks for day in week.get("days", [])]
    return {
        "weeks": len(weeks),
        "days": len(days),
        "exercises": sum(len(day.get("exercises", [])) for day in days),
        "exercise_names": list(
            dict.fromkeys(
                exercise.get("name", "")
                for day in days
                for exercise in day.get("exercises", [])
                if exercise.get("name")
            )
        ),
    }
