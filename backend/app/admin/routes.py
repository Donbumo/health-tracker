from datetime import datetime, timezone

from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.admin import admin_bp
from app.admin.forms import CreateUserForm
from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    MedicalLabReport,
    TrainingPlan,
    TrainingSession,
    UploadedFile,
    User,
    WeighIn,
)


def _require_admin() -> None:
    if not current_user.is_admin:
        abort(403)


def _users():
    return db.session.execute(
        db.select(User).order_by(User.created_at, User.id)
    ).scalars()


def _system_counts() -> dict[str, int]:
    models = {
        "users": User,
        "uploads": UploadedFile,
        "training_plans": TrainingPlan,
        "training_sessions": TrainingSession,
        "nutrition_days": DailyNutrition,
        "energy_days": DailyEnergy,
        "weigh_ins": WeighIn,
        "medical_reports": MedicalLabReport,
    }
    return {
        name: db.session.execute(db.select(func.count(model.id))).scalar_one()
        for name, model in models.items()
    }


@admin_bp.get("/users")
@login_required
def users():
    _require_admin()
    return render_template(
        "admin/users.html",
        users=_users(),
        form=CreateUserForm(),
    )


@admin_bp.get("/system")
@login_required
def system():
    _require_admin()
    try:
        db.session.execute(text("SELECT 1"))
        counts = _system_counts()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Admin system database check failed")
        database_status = "error"
        counts = None
    else:
        database_status = "ok"
    return render_template(
        "admin/system.html",
        database_status=database_status,
        app_version=current_app.config.get("APP_VERSION", "unknown"),
        counts=counts,
        server_time=datetime.now(timezone.utc),
    )


@admin_bp.post("/users/create")
@login_required
def create_user():
    _require_admin()
    form = CreateUserForm()
    if not form.validate_on_submit():
        return render_template("admin/users.html", users=_users(), form=form), 400

    email = form.email.data.strip().casefold()
    existing = db.session.execute(
        db.select(User).where(
            or_(
                User.email == email,
                func.lower(User.username) == email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        flash("Ya existe un usuario con ese email.", "danger")
        return redirect(url_for("admin.users"))

    user = User(username=email, email=email, role=form.role.data)
    user.set_password(form.password.data)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe un usuario con ese email.", "danger")
    else:
        flash(f"Usuario {email} creado correctamente.", "success")
    return redirect(url_for("admin.users"))
