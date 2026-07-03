from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField(
        "Usuario o email",
        validators=[DataRequired(), Length(max=254)],
        render_kw={"autocomplete": "username"},
    )
    password = PasswordField(
        "Contraseña",
        validators=[DataRequired()],
        render_kw={"autocomplete": "current-password"},
    )
    remember = BooleanField("Mantener sesión")
    submit = SubmitField("Entrar")


class LogoutForm(FlaskForm):
    submit = SubmitField("Cerrar sesión")
