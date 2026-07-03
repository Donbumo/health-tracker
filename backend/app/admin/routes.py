from flask import abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.admin import admin_bp
from app.admin.forms import CreateUserForm
from app.extensions import db
from app.models import User


def _require_admin() -> None:
    if not current_user.is_admin:
        abort(403)


def _users():
    return db.session.execute(
        db.select(User).order_by(User.created_at, User.id)
    ).scalars()


@admin_bp.get("/users")
@login_required
def users():
    _require_admin()
    return render_template(
        "admin/users.html",
        users=_users(),
        form=CreateUserForm(),
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
