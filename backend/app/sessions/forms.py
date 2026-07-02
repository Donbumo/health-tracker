from flask_wtf import FlaskForm
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
