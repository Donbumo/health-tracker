from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from flask import abort, flash, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.medical import medical_bp
from app.medical.forms import MedicalLabImportForm, MedicalLabManualForm
from app.models import MedicalLabReport
from app.services.files import UploadError, store_uploaded_file
from app.services.exporters.medical_lab import (
    MedicalLabCsvExporter,
    MedicalLabJsonExporter,
    MedicalMarkerHistoryCsvExporter,
)
from app.services.importers.medical_lab import (
    MedicalLabImportError,
    import_medical_lab_file,
)
from app.services.manual_json import (
    ManualJsonGenerationError,
    build_medical_lab_document,
    generate_standard_json,
)
from app.services.medical_history import (
    medical_marker_catalog,
    medical_marker_history,
)
from app.services.validation import JsonSchemaValidationError


def _user_report_or_404(report_id: int) -> MedicalLabReport:
    report = db.session.execute(
        db.select(MedicalLabReport).where(
            MedicalLabReport.id == report_id,
            MedicalLabReport.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if report is None:
        abort(404)
    return report


def _manual_value(raw_value: str) -> Decimal | str:
    normalized = raw_value.strip()
    try:
        numeric = Decimal(normalized)
    except InvalidOperation:
        return normalized
    return numeric if numeric.is_finite() else normalized


@medical_bp.get("/labs")
@login_required
def list_reports():
    reports = db.session.execute(
        db.select(MedicalLabReport)
        .where(MedicalLabReport.user_id == current_user.id)
        .order_by(MedicalLabReport.date.desc(), MedicalLabReport.id.desc())
    ).scalars()
    return render_template("medical/lab_list.html", reports=reports)


@medical_bp.route("/labs/import", methods=["GET", "POST"])
@login_required
def import_report():
    form = MedicalLabImportForm()
    if form.validate_on_submit():
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            report, report_duplicate = import_medical_lab_file(
                source_file,
                current_user.id,
            )
        except (UploadError, MedicalLabImportError, JsonSchemaValidationError) as error:
            flash(f"No fue posible importar el reporte: {error}", "danger")
        else:
            duplicate = file_duplicate or report_duplicate
            flash(
                "Este reporte ya había sido importado."
                if duplicate
                else "Reporte médico importado correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("medical.report_detail", report_id=report.id))
    return render_template("medical/lab_import.html", form=form)


@medical_bp.route("/labs/manual", methods=["GET", "POST"])
@login_required
def manual_report():
    form = MedicalLabManualForm()
    if not form.is_submitted():
        form.date.data = date.today()
    if form.validate_on_submit():
        document = build_medical_lab_document(
            user_id=current_user.id,
            report_date=form.date.data,
            laboratory_name=form.laboratory_name.data,
            doctor_name=form.doctor_name.data,
            marker_name=form.marker_name.data,
            marker_code=form.marker_code.data,
            marker_value=_manual_value(form.value.data),
            unit=form.unit.data,
            reference_min=form.reference_min.data,
            reference_max=form.reference_max.data,
            reference_text=form.reference_text.data,
            status=form.status.data,
            notes=form.notes.data,
            marker_notes=form.marker_notes.data,
        )
        filename = f"medical_lab_{form.date.data.isoformat()}.json"
        try:
            source_file, file_duplicate = generate_standard_json(
                document=document,
                schema_name="medical_lab",
                user_id=current_user.id,
                original_filename=filename,
            )
            report, report_duplicate = import_medical_lab_file(
                source_file,
                current_user.id,
            )
        except (
            ManualJsonGenerationError,
            MedicalLabImportError,
            JsonSchemaValidationError,
        ) as error:
            flash(f"No fue posible guardar el reporte: {error}", "danger")
        else:
            duplicate = file_duplicate or report_duplicate
            flash(
                "Este reporte ya estaba registrado."
                if duplicate
                else "Reporte médico guardado correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("medical.report_detail", report_id=report.id))
    return render_template("medical/lab_manual.html", form=form)


@medical_bp.get("/labs/<int:report_id>")
@login_required
def report_detail(report_id: int):
    return render_template(
        "medical/lab_detail.html",
        report=_user_report_or_404(report_id),
    )


@medical_bp.get("/labs/<int:report_id>/export.json")
@login_required
def export_report_json(report_id: int):
    report = _user_report_or_404(report_id)
    artifact = MedicalLabJsonExporter().export(report, current_user.id)
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=f"medical_lab_{report.date.isoformat()}_{report.id}.json",
    )


@medical_bp.get("/labs/<int:report_id>/export.csv")
@login_required
def export_report_csv(report_id: int):
    report = _user_report_or_404(report_id)
    artifact = MedicalLabCsvExporter().export(report, current_user.id)
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=f"medical_lab_{report.date.isoformat()}_{report.id}.csv",
    )


@medical_bp.get("/markers")
@login_required
def marker_list():
    return render_template(
        "medical/marker_list.html",
        markers=medical_marker_catalog(current_user.id),
    )


@medical_bp.get("/markers/<path:marker_name>")
@login_required
def marker_detail(marker_name: str):
    history = medical_marker_history(current_user.id, marker_name)
    if not history:
        abort(404)
    return render_template(
        "medical/marker_detail.html",
        marker_name=history[-1]["result"].marker_name,
        history=reversed(history),
    )


@medical_bp.get("/markers/<path:marker_name>/export.csv")
@login_required
def export_marker_csv(marker_name: str):
    history = medical_marker_history(current_user.id, marker_name)
    if not history:
        abort(404)
    artifact = MedicalMarkerHistoryCsvExporter().export(history, current_user.id)
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name="medical_marker_history.csv",
    )
