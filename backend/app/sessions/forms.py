from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateTimeLocalField,
    DecimalField,
    HiddenField,
    IntegerField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class TrainingSessionForm(FlaskForm):
    planned_day = HiddenField(validators=[DataRequired()])
    performed_at = DateTimeLocalField(
        "Fecha y hora",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )
    duration_minutes = IntegerField(
        "Duración total (minutos)",
        validators=[Optional(), NumberRange(min=1, max=10080)],
    )
    average_heart_rate_bpm = IntegerField(
        "Frecuencia cardiaca promedio (bpm)",
        validators=[Optional(), NumberRange(min=20, max=250)],
    )
    calories_burned = DecimalField(
        "Calorías estimadas/gastadas",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=100000)],
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
