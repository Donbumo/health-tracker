from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.main import main_bp
from app.main.forms import UploadForm
from app.models import UploadedFile
from app.services.files import UploadError, store_uploaded_file


def _current_user_files():
    return db.session.execute(
        db.select(UploadedFile)
        .where(UploadedFile.user_id == current_user.id)
        .order_by(UploadedFile.created_at.desc())
    ).scalars()


@main_bp.get("/")
@login_required
def index():
    return render_template("index.html", files=_current_user_files())


@main_bp.route("/uploads", methods=["GET", "POST"])
@login_required
def uploads():
    form = UploadForm()
    if form.validate_on_submit():
        try:
            record, duplicate = store_uploaded_file(form.file.data, current_user.id)
        except UploadError as error:
            flash(str(error), "danger")
        else:
            if duplicate:
                flash(
                    f"'{record.original_filename}' ya estaba registrado para tu usuario.",
                    "warning",
                )
            else:
                flash("Archivo guardado correctamente.", "success")
            return redirect(url_for("main.uploads"))

    return render_template("uploads/upload.html", form=form, files=_current_user_files())
