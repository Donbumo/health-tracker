from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


class TrainingPlanImportForm(FlaskForm):
    file = FileField(
        "Rutina JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    submit = SubmitField("Importar rutina")


class TrainingPlanVersionForm(FlaskForm):
    file = FileField(
        "Nueva versión JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    change_reason = TextAreaField(
        "Motivo del cambio",
        validators=[DataRequired(), Length(min=3, max=2000)],
    )
    submit = SubmitField("Crear versión")


class ActivateTrainingPlanVersionForm(FlaskForm):
    submit = SubmitField("Activar versión")
