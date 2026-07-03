from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.body import body_bp
from app.body.forms import WeighInImportForm
from app.extensions import db
from app.models import WeighIn
from app.services.files import UploadError, mark_import_status, store_uploaded_file
from app.services.importers.weigh_in import (
    WeighInImportError,
    import_weigh_in_file,
)
from app.services.validation import JsonSchemaValidationError


def _user_weigh_in_or_404(record_id: int) -> WeighIn:
    record = db.session.execute(
        db.select(WeighIn).where(
            WeighIn.id == record_id,
            WeighIn.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return record


@body_bp.get("/weigh-ins")
@login_required
def list_weigh_ins():
    records = db.session.execute(
        db.select(WeighIn)
        .where(WeighIn.user_id == current_user.id)
        .order_by(WeighIn.recorded_at.desc())
    ).scalars()
    return render_template("body/weigh_in_list.html", records=records)


@body_bp.route("/weigh-ins/import", methods=["GET", "POST"])
@login_required
def import_weigh_in():
    form = WeighInImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            record, record_duplicate = import_weigh_in_file(
                source_file,
                current_user.id,
            )
        except (WeighInImportError, JsonSchemaValidationError, UploadError) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="weigh_in",
                    error_message=str(error),
                )
            flash(f"No fue posible importar el pesaje: {error}", "danger")
        else:
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="weigh_in",
            )
            flash(
                "Ese pesaje ya había sido importado."
                if duplicate
                else "Pesaje importado correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("body.weigh_in_detail", record_id=record.id))
    return render_template("body/weigh_in_import.html", form=form)


@body_bp.get("/weigh-ins/<int:record_id>")
@login_required
def weigh_in_detail(record_id: int):
    return render_template(
        "body/weigh_in_detail.html",
        record=_user_weigh_in_or_404(record_id),
    )
