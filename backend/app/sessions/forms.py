from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateTimeLocalField, HiddenField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class TrainingSessionForm(FlaskForm):
    planned_day = HiddenField(validators=[DataRequired()])
    performed_at = DateTimeLocalField(
        "Fecha y hora",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )
    notes = TextAreaField(
        "Notas de la sesión",
        validators=[Optional(), Length(max=5000)],
    )
    submit = SubmitField("Guardar sesión")


class CompletedWorkoutImportForm(FlaskForm):
    file = FileField(
        "Sesión JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    submit = SubmitField("Importar sesión")
