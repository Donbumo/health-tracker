from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import IntegerField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class TrainingPlanImportForm(FlaskForm):
    file = FileField(
        "Rutina JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    submit = SubmitField("Importar rutina")


class TrainingPlanCreateForm(FlaskForm):
    name = StringField("Nombre de la rutina", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("Descripción", validators=[Optional(), Length(max=5000)])
    day_name = StringField("Nombre del primer día", validators=[DataRequired(), Length(max=200)])
    exercise_name = StringField("Primer ejercicio", validators=[DataRequired(), Length(max=200)])
    set_count = IntegerField(
        "Series",
        validators=[DataRequired(), NumberRange(min=1, max=20)],
        default=3,
    )
    target_reps = IntegerField(
        "Repeticiones objetivo",
        validators=[DataRequired(), NumberRange(min=1, max=1000)],
        default=8,
    )
    rest_seconds = IntegerField(
        "Descanso entre series (segundos)",
        validators=[Optional(), NumberRange(min=0, max=86400)],
        default=120,
    )
    submit = SubmitField("Crear rutina")


class DuplicateTrainingPlanForm(FlaskForm):
    name = StringField("Nombre de la copia", validators=[DataRequired(), Length(max=200)])
    submit = SubmitField("Duplicar rutina")


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
