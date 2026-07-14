from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class PlannedWorkoutForm(FlaskForm):
    planned_day = SelectField("Día de rutina", validators=[DataRequired()])
    scheduled_for_date = DateField("Fecha", validators=[DataRequired()])
    timezone = StringField(
        "Zona horaria IANA", validators=[DataRequired(), Length(max=64)]
    )
    submit = SubmitField("Planificar entrenamiento")


class PlannedWorkoutRescheduleForm(FlaskForm):
    scheduled_for_date = DateField("Nueva fecha", validators=[DataRequired()])
    timezone = StringField(
        "Zona horaria IANA", validators=[DataRequired(), Length(max=64)]
    )
    submit = SubmitField("Reprogramar")


class PlannedWorkoutActionForm(FlaskForm):
    submit = SubmitField("Actualizar")
