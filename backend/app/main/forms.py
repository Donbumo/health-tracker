from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateTimeLocalField, DecimalField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


def finite_decimal(_form, field) -> None:
    if field.data is not None and not field.data.is_finite():
        raise ValidationError("Ingresa un número finito.")


class UploadForm(FlaskForm):
    file = FileField("Archivo", validators=[FileRequired()])
    submit = SubmitField("Subir archivo")


class UserDataPreviewForm(FlaskForm):
    file = FileField(
        "Export JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    submit = SubmitField("Validar sin importar")


class WeighInForm(FlaskForm):
    recorded_at = DateTimeLocalField(
        "Fecha y hora",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )
    weight_kg = DecimalField(
        "Peso (kg)",
        validators=[DataRequired(), finite_decimal, NumberRange(min=0.01, max=1000)],
        render_kw={"min": "0.01", "max": "1000", "step": "0.01"},
    )
    body_fat_percent = DecimalField(
        "Grasa corporal (%)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100)],
        render_kw={"min": "0", "max": "100", "step": "0.1"},
    )
    muscle_mass_kg = DecimalField(
        "Masa muscular (kg)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.01"},
    )
    water_percent = DecimalField(
        "Agua corporal (%)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100)],
        render_kw={"min": "0", "max": "100", "step": "0.1"},
    )
    visceral_fat = DecimalField(
        "Grasa visceral",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.1"},
    )
    bmr_kcal = DecimalField(
        "Metabolismo basal (kcal)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000)],
        render_kw={"min": "0", "max": "100000", "step": "1"},
    )
    bmi = DecimalField(
        "BMI / IMC",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.01"},
    )
    notes = TextAreaField("Notas", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Guardar pesaje")
