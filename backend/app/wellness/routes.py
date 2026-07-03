from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import DailyEnergy
from app.services.files import UploadError, mark_import_status, store_uploaded_file
from app.services.importers.daily_energy import (
    DailyEnergyImportError,
    import_daily_energy_file,
)
from app.services.validation import JsonSchemaValidationError
from app.wellness import wellness_bp
from app.wellness.forms import DailyEnergyImportForm


def _user_energy_or_404(record_id: int) -> DailyEnergy:
    record = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.id == record_id,
            DailyEnergy.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return record


@wellness_bp.get("/daily-energy")
@login_required
def energy_list():
    records = db.session.execute(
        db.select(DailyEnergy)
        .where(DailyEnergy.user_id == current_user.id)
        .order_by(DailyEnergy.date.desc())
    ).scalars()
    return render_template("wellness/energy_list.html", records=records)


@wellness_bp.route("/daily-energy/import", methods=["GET", "POST"])
@login_required
def energy_import():
    form = DailyEnergyImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            record, record_duplicate = import_daily_energy_file(
                source_file,
                current_user.id,
            )
        except (DailyEnergyImportError, JsonSchemaValidationError, UploadError) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="daily_energy",
                    error_message=str(error),
                )
            flash(f"No fue posible importar la energía diaria: {error}", "danger")
        else:
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="daily_energy",
            )
            flash(
                "Ese archivo de energía ya había sido importado."
                if duplicate
                else "Energía diaria importada correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("wellness.energy_detail", record_id=record.id))
    return render_template("wellness/energy_import.html", form=form)


@wellness_bp.get("/daily-energy/<int:record_id>")
@login_required
def energy_detail(record_id: int):
    return render_template(
        "wellness/energy_detail.html",
        record=_user_energy_or_404(record_id),
    )
