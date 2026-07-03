from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp


class CreateUserForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired(),
            Length(max=254),
            Regexp(
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
                message="Ingresa un email válido.",
            ),
        ],
        render_kw={"autocomplete": "email"},
    )
    password = PasswordField(
        "Contraseña temporal",
        validators=[DataRequired(), Length(min=12, max=128)],
        render_kw={"autocomplete": "new-password"},
    )
    role = SelectField(
        "Rol",
        choices=(("user", "Usuario"), ("admin", "Administrador")),
        validators=[DataRequired()],
    )
    submit = SubmitField("Crear usuario")
