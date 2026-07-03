from urllib.parse import urlsplit

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_

from app.auth import auth_bp
from app.auth.forms import LoginForm, LogoutForm
from app.extensions import db
from app.models import User


def _safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    parsed = urlsplit(target)
    return (
        not parsed.scheme
        and not parsed.netloc
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user = db.session.execute(
            db.select(User).where(
                or_(
                    User.username == username,
                    User.email == username.casefold(),
                )
            )
        ).scalar_one_or_none()

        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_url = request.args.get("next")
            destination = next_url if _safe_next_url(next_url) else url_for("main.index")
            return redirect(destination)

        flash("Usuario o contraseña incorrectos.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
def logout():
    form = LogoutForm()
    if form.validate_on_submit():
        logout_user()
        flash("Sesión cerrada.", "success")
        return redirect(url_for("auth.login"))
    return "Solicitud inválida", 400
