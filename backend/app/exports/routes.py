from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.exports import exports_bp
from app.extensions import db
from app.models import Activity, ExportRecord, Route, TrainingPlan, TrainingSession
from app.services.export_artifacts import ExportArtifactService, ExportStorageError
from app.services.exporters import ExportError, ExporterRegistry


DOMAIN_MODELS = {
    "activity": Activity,
    "route": Route,
    "training_plan": TrainingPlan,
    "training_session": TrainingSession,
}


@exports_bp.get("/exports")
@login_required
def history():
    records = db.session.execute(
        db.select(ExportRecord)
        .where(ExportRecord.user_id == current_user.id)
        .order_by(ExportRecord.created_at.desc(), ExportRecord.id.desc())
    ).scalars().all()
    return render_template("exports/history.html", records=records)


@exports_bp.route("/exports/new/<string:domain>/<int:source_id>", methods=["GET", "POST"])
@login_required
def create(domain: str, source_id: int):
    resource = _resource_or_404(domain, source_id)
    registry = ExporterRegistry()
    service = ExportArtifactService()
    context = _context()

    if request.method == "POST":
        format_name = request.form.get("format", "").strip()
        try:
            spec = registry.get(domain, format_name)
            record = service.generate(
                spec,
                resource,
                user_id=current_user.id,
                source_type=domain,
                source_id=source_id,
                context=context,
            )
        except ExportError as error:
            flash(str(error), "danger")
        else:
            flash("Export generado y registrado.", "success")
            return redirect(url_for("exports.detail", export_id=record.id))

    previews = []
    for spec in registry.formats_for(domain):
        try:
            preview = service.preview(spec, resource, user_id=current_user.id, context=context)
        except ExportError as error:
            preview = None
            error_message = str(error)
        else:
            error_message = None
        previews.append({"spec": spec, "preview": preview, "error": error_message})
    versions = resource.versions if isinstance(resource, TrainingPlan) else ()
    return render_template(
        "exports/create.html",
        resource=resource,
        domain=domain,
        source_id=source_id,
        previews=previews,
        context=context,
        versions=versions,
    )


@exports_bp.get("/exports/<int:export_id>")
@login_required
def detail(export_id: int):
    return render_template("exports/detail.html", record=_record_or_404(export_id))


@exports_bp.get("/exports/<int:export_id>/download")
@login_required
def download(export_id: int):
    record = _record_or_404(export_id)
    try:
        path = ExportArtifactService().resolve_download(record, user_id=current_user.id)
    except ExportStorageError:
        abort(404)
    response = send_file(
        path,
        mimetype=record.media_type,
        as_attachment=True,
        download_name=record.filename,
        conditional=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@exports_bp.post("/exports/<int:export_id>/delete")
@login_required
def delete(export_id: int):
    record = _record_or_404(export_id)
    try:
        ExportArtifactService().delete(record, user_id=current_user.id)
    except ExportStorageError as error:
        flash(str(error), "danger")
    else:
        flash("Export eliminado del storage gestionado.", "success")
    return redirect(url_for("exports.history"))


def _resource_or_404(domain: str, source_id: int):
    model = DOMAIN_MODELS.get(domain)
    if model is None:
        abort(404)
    resource = db.session.execute(
        db.select(model).where(model.id == source_id, model.user_id == current_user.id)
    ).scalar_one_or_none()
    if resource is None:
        abort(404)
    return resource


def _record_or_404(export_id: int) -> ExportRecord:
    record = db.session.execute(
        db.select(ExportRecord).where(
            ExportRecord.id == export_id,
            ExportRecord.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return record


def _context() -> dict[str, str]:
    return {
        key: value.strip()
        for key in ("version_id", "week_number", "day_number")
        if (value := request.values.get(key, "")).strip()
    }
