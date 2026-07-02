from io import BytesIO

from flask import abort, flash, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import TrainingPlan
from app.services.files import UploadError, store_uploaded_file
from app.services.training_plans import (
    TrainingPlanImportError,
    get_active_version,
    import_training_plan,
    serialize_training_plan,
)
from app.services.validation import JsonSchemaValidationError
from app.training import training_bp
from app.training.forms import TrainingPlanImportForm


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


@training_bp.get("")
@login_required
def list_plans():
    plans = db.session.execute(
        db.select(TrainingPlan)
        .where(TrainingPlan.user_id == current_user.id)
        .order_by(TrainingPlan.updated_at.desc())
    ).scalars()
    return render_template("training/list.html", plans=plans)


@training_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_plan():
    form = TrainingPlanImportForm()
    if form.validate_on_submit():
        try:
            source_file, _file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            plan, plan_duplicate = import_training_plan(source_file, current_user.id)
        except (UploadError, TrainingPlanImportError, JsonSchemaValidationError) as error:
            flash(f"No fue posible importar la rutina: {error}", "danger")
        else:
            if plan_duplicate:
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
    )


@training_bp.get("/<int:plan_id>/export")
@login_required
def export_active(plan_id: int):
    plan = _user_plan_or_404(plan_id)
    active_version = get_active_version(plan, current_user.id)
    filename_base = secure_filename(plan.name) or f"training_plan_{plan.id}"
    return send_file(
        BytesIO(serialize_training_plan(active_version.content)),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"{filename_base}_v{active_version.version_number}.json",
    )
